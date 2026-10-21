import AVFoundation
import NoahCore
import Speech
import SwiftUI

/// Microfone da aba Central. O reconhecimento roda só no aparelho
/// (`requiresOnDeviceRecognition`): se o português não estiver disponível
/// offline, a escuta fica indisponível em vez de mandar áudio para fora.
/// Cada frase fechada por uma pausa (`TurnoDeVoz`) vai para `aoFechar`.
@MainActor @Observable
final class Ouvido {
    enum Estado: Equatable {
        case desligado, ouvindo
        case semPermissao(String), indisponivel(String)
    }

    private(set) var estado: Estado = .desligado
    /// O que já foi entendido da frase em andamento.
    private(set) var parcial = ""
    /// Volume do microfone, de 0 a 1, para o rosto pulsar.
    private(set) var nivel: Double = 0
    private(set) var falando = false

    var mudo: Bool {
        didSet { UserDefaults.standard.set(mudo, forKey: "noah.voz.mudo") }
    }
    var falarRespostas: Bool {
        didSet { UserDefaults.standard.set(falarRespostas, forKey: "noah.voz.falar") }
    }

    /// Recebe cada frase pronta.
    var aoFechar: (String) -> Void = { _ in }

    private let reconhecedor = SFSpeechRecognizer(locale: Locale(identifier: "pt-BR"))
    private let motor = AVAudioEngine()
    private let caixa = Caixa()
    private let falador = Falador()
    private var tarefa: SFSpeechRecognitionTask?
    private var turno = TurnoDeVoz()
    private var relogio: Task<Void, Never>?
    /// Ignora resultados atrasados de um pedido que já foi trocado.
    private var geracao = 0
    /// O que a tela quer agora; `ligar` confere de novo depois de cada espera.
    private var querOuvir = false

    init() {
        let d = UserDefaults.standard
        mudo = d.bool(forKey: "noah.voz.mudo")
        falarRespostas = d.object(forKey: "noah.voz.falar") as? Bool ?? true
    }

    /// Liga ou desliga o microfone conforme a tela (mudo, digitando, Noah ocupado).
    func ajustar(ouvir: Bool) {
        querOuvir = ouvir
        if ouvir {
            Task { await ligar() }
        } else {
            desligar()
        }
    }

    func falar(_ texto: String) {
        guard !texto.isEmpty else { return }
        falando = true
        Task {
            await falador.falar(texto)
            falando = false
        }
    }

    func calar() {
        falador.parar()
    }

    // MARK: - Microfone

    private func ligar() async {
        guard querOuvir, estado != .ouvindo else { return }
        guard await permitido() else { return }
        guard let reconhecedor, reconhecedor.supportsOnDeviceRecognition else {
            estado = .indisponivel("Este aparelho não reconhece português sem internet. Use a setinha para digitar.")
            return
        }
        guard reconhecedor.isAvailable else {
            estado = .indisponivel("O reconhecimento de voz está ocupado agora. Tente de novo em instantes.")
            return
        }
        // A permissão pode ter demorado; a tela pode ter mudado de ideia.
        guard querOuvir, estado != .ouvindo else { return }

        do {
            #if os(iOS)
            let sessao = AVAudioSession.sharedInstance()
            try sessao.setCategory(.playAndRecord, mode: .measurement, options: [.defaultToSpeaker, .duckOthers])
            try sessao.setActive(true, options: .notifyOthersOnDeactivation)
            #endif
            let entrada = motor.inputNode
            let formato = entrada.outputFormat(forBus: 0)
            let caixa = caixa
            entrada.removeTap(onBus: 0)
            entrada.installTap(onBus: 0, bufferSize: 1024, format: formato) { buffer, _ in
                caixa.receber(buffer)
            }
            motor.prepare()
            try motor.start()
        } catch {
            motor.inputNode.removeTap(onBus: 0)
            estado = .indisponivel("Não consegui abrir o microfone: \(error.localizedDescription)")
            return
        }
        estado = .ouvindo
        novoPedido()
        relogio = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                self?.tique()
            }
        }
    }

    private func desligar() {
        relogio?.cancel()
        relogio = nil
        geracao += 1
        tarefa?.cancel()
        tarefa = nil
        caixa.trocar(nil)
        if motor.isRunning { motor.stop() }
        motor.inputNode.removeTap(onBus: 0)
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
        turno.descartar()
        parcial = ""
        nivel = 0
        if estado == .ouvindo { estado = .desligado }
    }

    /// Começa uma frase nova: o reconhecedor acumula texto por pedido.
    private func novoPedido() {
        tarefa?.cancel()
        geracao += 1
        let minha = geracao
        let pedido = SFSpeechAudioBufferRecognitionRequest()
        pedido.requiresOnDeviceRecognition = true
        pedido.shouldReportPartialResults = true
        pedido.addsPunctuation = true
        caixa.trocar(pedido)
        tarefa = reconhecedor?.recognitionTask(with: pedido) { [weak self] resultado, erro in
            let texto = resultado?.bestTranscription.formattedString
            let acabou = erro != nil || (resultado?.isFinal ?? false)
            Task { @MainActor in
                self?.recebeu(texto, acabou: acabou, geracao: minha)
            }
        }
    }

    private func recebeu(_ texto: String?, acabou: Bool, geracao dele: Int) {
        guard dele == geracao, estado == .ouvindo else { return }
        if let texto {
            turno.ouviu(texto, em: .now)
            parcial = turno.parcial
        }
        // Erro ou fim do pedido (silêncio longo, limite do sistema): fecha o
        // que já foi ouvido e segue escutando com um pedido novo.
        if acabou {
            if let frase = turno.fechar(em: .distantFuture) { aoFechar(frase) }
            parcial = ""
            novoPedido()
        }
    }

    private func tique() {
        guard estado == .ouvindo else { return }
        nivel = nivel * 0.5 + caixa.nivel * 0.5
        if let frase = turno.fechar(em: .now) {
            parcial = ""
            novoPedido()
            aoFechar(frase)
        }
    }

    private func permitido() async -> Bool {
        let voz = await withCheckedContinuation { (c: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0) }
        }
        guard voz == .authorized else {
            estado = .semPermissao("Sem permissão de reconhecimento de voz. Libere o Noah em Ajustes > Privacidade.")
            return false
        }
        #if os(iOS)
        let microfone = await AVAudioApplication.requestRecordPermission()
        #else
        let microfone = await AVCaptureDevice.requestAccess(for: .audio)
        #endif
        guard microfone else {
            estado = .semPermissao("Sem permissão de microfone. Libere o Noah em Ajustes > Privacidade > Microfone.")
            return false
        }
        return true
    }
}

/// Ponte entre a thread de áudio e o pedido de reconhecimento atual.
private final class Caixa: @unchecked Sendable {
    private let trava = NSLock()
    private var pedido: SFSpeechAudioBufferRecognitionRequest?
    private var _nivel: Double = 0

    var nivel: Double { trava.withLock { _nivel } }

    func trocar(_ novo: SFSpeechAudioBufferRecognitionRequest?) {
        trava.withLock {
            pedido?.endAudio()
            pedido = novo
        }
    }

    func receber(_ buffer: AVAudioPCMBuffer) {
        var rms: Double = 0
        if let canal = buffer.floatChannelData?[0], buffer.frameLength > 0 {
            var soma: Float = 0
            for i in 0..<Int(buffer.frameLength) { soma += canal[i] * canal[i] }
            rms = Double((soma / Float(buffer.frameLength)).squareRoot())
        }
        trava.withLock {
            pedido?.append(buffer)
            // Fala normal fica perto de 0,05–0,1 de RMS.
            _nivel = min(1, rms * 12)
        }
    }
}

/// Voz do sistema em português para ler a resposta do Noah.
private final class Falador: NSObject, AVSpeechSynthesizerDelegate, @unchecked Sendable {
    private let sintetizador = AVSpeechSynthesizer()
    private var fim: CheckedContinuation<Void, Never>?

    override init() {
        super.init()
        sintetizador.delegate = self
    }

    @MainActor
    func falar(_ texto: String) async {
        parar()
        let fala = AVSpeechUtterance(string: texto)
        fala.voice = AVSpeechSynthesisVoice(language: "pt-BR")
        await withCheckedContinuation { c in
            fim = c
            sintetizador.speak(fala)
        }
    }

    func parar() {
        if sintetizador.isSpeaking { sintetizador.stopSpeaking(at: .immediate) }
        terminar()
    }

    private func terminar() {
        fim?.resume()
        fim = nil
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) { terminar() }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) { terminar() }
}
