import AVFoundation
import Foundation
import NoahCore

/// Plays the already installed cloned voice from the authenticated Mac hub.
/// Audio is PCM16 mono at 24 kHz, framed by a big-endian UInt32 length.
/// A complete validated reply plays continuously, even when generation is slower
/// than real time. Network parsing runs outside the main actor.
@MainActor
final class VozDaCentral {
    private let motor: AVAudioEngine
    private let player = AVAudioPlayerNode()
    private let formato = AVAudioFormat(standardFormatWithSampleRate: 24_000, channels: 1)!
    private var tarefa: Task<Void, Error>?
    private var geracao = UUID()
    private var pendentes = 0

    init(motor: AVAudioEngine) {
        self.motor = motor
        motor.attach(player)
        motor.connect(player, to: motor.mainMixerNode, format: formato)
    }

    func falar(_ texto: String) async throws {
        parar()
        let id = geracao
        let nova = Task { try await transmitir(texto, id: id) }
        tarefa = nova
        try await withTaskCancellationHandler {
            try await nova.value
        } onCancel: {
            nova.cancel()
        }
    }

    func parar() {
        geracao = UUID()
        tarefa?.cancel()
        tarefa = nil
        player.stop()
        pendentes = 0
    }

    private func transmitir(_ texto: String, id: UUID) async throws {
        defer { if geracao == id { player.stop(); pendentes = 0 } }
        let cliente = try Ajustes.cliente()
        var req = URLRequest(url: cliente.base.appendingPathComponent("central/api/voz"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = cliente.token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["texto": String(texto.prefix(1500))])
        req.timeoutInterval = 60
        let dados = try await Self.carregar(req)
        try Task.checkCancellation()
        guard geracao == id else { throw CancellationError() }
        try agendar(dados, id: id)
        while pendentes > 0, geracao == id {
            try await Task.sleep(for: .milliseconds(20))
        }
        try Task.checkCancellation()
        if geracao == id { player.stop() }
    }

    /// Keep byte-by-byte transport work off the UI/audio scheduling actor.
    nonisolated private static func carregar(_ req: URLRequest) async throws -> Data {
        let (bytes, resposta) = try await URLSession.shared.bytes(for: req)
        guard let http = resposta as? HTTPURLResponse, http.statusCode == 200,
              http.value(forHTTPHeaderField: "Content-Type") == "application/vnd.noah.pcm" else {
            throw ErroCentral.servidor(status: (resposta as? HTTPURLResponse)?.statusCode ?? 503,
                                       mensagem: "A voz clonada não está disponível no Mac")
        }
        var dados = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard dados.count < 40_100_000 else { throw ErroCentral.rede("Áudio da voz grande demais") }
            dados.append(byte)
        }
        return try AudioDaCentral.pcm(dados)
    }

    private func agendar(_ dados: Data, id: UUID) throws {
        guard !dados.isEmpty else { return }
        let count = dados.count / 2
        guard let buffer = AVAudioPCMBuffer(pcmFormat: formato, frameCapacity: AVAudioFrameCount(count)),
              let canal = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(count)
        dados.withUnsafeBytes { raw in
            for i in 0..<count {
                let sample = Int16(littleEndian: raw.loadUnaligned(fromByteOffset: i * 2, as: Int16.self))
                canal[i] = Float(sample) / 32768
            }
        }
        if !motor.isRunning { try motor.start() }
        pendentes += 1
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.geracao == id else { return }
                self.pendentes = max(0, self.pendentes - 1)
            }
        }
        if !player.isPlaying { player.play() }
    }
}
