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
    private(set) var avisoVoz: String?

    var mudo: Bool {
        didSet { UserDefaults.standard.set(mudo, forKey: "noah.voz.mudo") }
    }
    var falarRespostas: Bool {
        didSet { UserDefaults.standard.set(falarRespostas, forKey: "noah.voz.falar") }
    }

    /// Recebe cada frase pronta.
    var aoFechar: (String) -> Void = { _ in }
    /// Chamado quando reconhecimento local confirma o início de uma fala.
    /// A tela usa isso para interromper a resposta sem descartar a fala nova.
    var aoIniciarFala: () -> Void = {}

    private let reconhecedor = SFSpeechRecognizer(locale: Locale(identifier: "pt-BR"))
    private let motor: AVAudioEngine
    private let caixa = Caixa()
    private let falador: Falador
    private var tarefa: SFSpeechRecognitionTask?
    private var turno = TurnoDeVoz()
    private var relogio: Task<Void, Never>?
    /// Ignora resultados atrasados de um pedido que já foi trocado.
    private var geracao = 0
    /// O que a tela quer agora; `ligar` confere de novo depois de cada espera.
    private var querOuvir = false
    private var acionouBargeIn = false
    private var geracaoDeFala = UUID()

    init() {
        let motor = AVAudioEngine()
        self.motor = motor
        falador = Falador(motor: motor)
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
        geracaoDeFala = UUID()
        let minhaFala = geracaoDeFala
        falando = true
        Task {
            let clonada = await falador.falar(texto)
            guard geracaoDeFala == minhaFala else { return }
            avisoVoz = clonada ? nil : "Voz clonada indisponível no Mac; usando a voz do aparelho."
            falando = false
        }
    }

    func calar() {
        geracaoDeFala = UUID()
        falando = false
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
            _ = falador
            #if os(iOS)
            let sessao = AVAudioSession.sharedInstance()
            try sessao.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .duckOthers])
            try sessao.setActive(true, options: .notifyOthersOnDeactivation)
            #endif
            let entrada = motor.inputNode
            // O modo de voz do AVAudioEngine reduz o retorno do alto-falante
            // ao microfone durante a leitura, permitindo interrompê-la falando.
            try? entrada.setVoiceProcessingEnabled(true)
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
        acionouBargeIn = false
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
        // Vocabulário recorrente ajuda o reconhecedor local sem reescrever
        // o que foi ouvido ("o pai" também pode ser uma frase legítima).
        pedido.contextualStrings = [
            "Noah", "Nicolas", "Nicholas", "Jarvis", "Cérebro",
            "opa", "opa, beleza?", "opa, tudo bem?", "e aí, beleza?", "beleza"
        ]
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
        if let texto, caixa.teveVozNoPedido, TurnoDeVoz.pareceFala(texto) {
            turno.ouviu(texto, em: .now)
            parcial = turno.parcial
            if !acionouBargeIn {
                acionouBargeIn = true
                aoIniciarFala()
            }
        }
        // Erro ou fim do pedido (silêncio longo, limite do sistema): fecha o
        // que já foi ouvido e segue escutando com um pedido novo.
        if acabou {
            if let frase = turno.fechar(em: .distantFuture) { aoFechar(frase) }
            parcial = ""
            acionouBargeIn = false
            novoPedido()
        }
    }

    private func tique() {
        guard estado == .ouvindo else { return }
        nivel = nivel * 0.5 + caixa.nivel * 0.5
        if let frase = turno.fechar(em: .now) {
            parcial = ""
            acionouBargeIn = false
            novoPedido()
            aoFechar(frase)
        } else if turno.parcial.isEmpty {
            acionouBargeIn = false
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
    private var detector = DetectorDeVoz()

    var nivel: Double { trava.withLock { _nivel } }
    var teveVozNoPedido: Bool { trava.withLock { detector.teveVozNoPedido } }

    func trocar(_ novo: SFSpeechAudioBufferRecognitionRequest?) {
        trava.withLock {
            pedido?.endAudio()
            pedido = novo
            detector.novoPedido()
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
            detector.atualizar(rms: rms)
            _nivel = min(1, rms * 12)
        }
    }
}

/// Prioriza a voz clonada da Central; a voz do aparelho cobre indisponibilidade.
@MainActor private final class Falador: NSObject, @preconcurrency AVSpeechSynthesizerDelegate {
    private let sintetizador = AVSpeechSynthesizer()
    private let central: VozDaCentral
    private var geracao = UUID()
    private var fim: CheckedContinuation<Void, Never>?
    private var utteranceAtiva: AVSpeechUtterance?

    init(motor: AVAudioEngine) {
        central = VozDaCentral(motor: motor)
        super.init()
        sintetizador.delegate = self
    }

    @MainActor
    func falar(_ texto: String) async -> Bool {
        parar()
        let id = geracao
        do {
            try await central.falar(texto)
            return true
        } catch {
            guard id == geracao, !Task.isCancelled else { return true }
        }
        let fala = AVSpeechUtterance(string: texto)
        fala.voice = AVSpeechSynthesisVoice(identifier: "com.apple.voice.enhanced.pt-BR.Felipe")
            ?? AVSpeechSynthesisVoice(language: "pt-BR")
        await withCheckedContinuation { c in
            fim = c
            utteranceAtiva = fala
            sintetizador.speak(fala)
        }
        return false
    }

    func parar() {
        geracao = UUID()
        central.parar()
        // Invalida antes do stop: o callback didCancel pode chegar depois que
        // uma fala nova já instalou outra continuation.
        utteranceAtiva = nil
        if sintetizador.isSpeaking { sintetizador.stopSpeaking(at: .immediate) }
        terminar()
    }

    private func terminar() {
        fim?.resume()
        fim = nil
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        guard u === utteranceAtiva else { return }
        utteranceAtiva = nil
        terminar()
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) {
        guard u === utteranceAtiva else { return }
        utteranceAtiva = nil
        terminar()
    }
}
