import NoahCore
import SwiftUI

/// Conversa da aba Central. Abre por voz: o Noah fica grande, ouvindo, e
/// responde em voz alta. A setinha embaixo sobe o chat para digitar; o
/// histórico é o mesmo nos dois modos.
struct ConversaVoz: View {
    @Environment(Modelo.self) private var modelo
    @State private var ouvido = Ouvido()
    @State private var digitando = false

    var body: some View {
        Group {
            if digitando {
                ChatDigitado(ouvido: ouvido) { digitando = false }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            } else {
                PalcoDeVoz(ouvido: ouvido) { digitando = true }
                    .transition(.opacity)
            }
        }
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: digitando)
        .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Paleta.noah.opacity(0.25)))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .onAppear {
            ouvido.aoFechar = { frase in
                Task { await modelo.conversar(frase) }
            }
            atualizar()
        }
        .onDisappear {
            ouvido.ajustar(ouvir: false)
            ouvido.calar()
        }
        .onChange(of: digitando) {
            if digitando { ouvido.calar() }
            atualizar()
        }
        .onChange(of: ouvido.mudo) { atualizar() }
        .onChange(of: ouvido.falando) { atualizar() }
        .onChange(of: modelo.conversando) { _, agora in
            if !agora { responderEmVoz() }
            atualizar()
        }
    }

    /// Microfone aberto só quando faz sentido: fora do modo digitação, sem
    /// mudo, e nunca enquanto o Noah pensa ou fala (para não ouvir a si mesmo).
    private func atualizar() {
        ouvido.ajustar(ouvir: !digitando && !ouvido.mudo && !modelo.conversando && !ouvido.falando)
    }

    private func responderEmVoz() {
        guard !digitando, ouvido.falarRespostas,
              let ultima = modelo.mensagens.last, ultima.autor == .noah else { return }
        ouvido.falar(FalaDoNoah.paraFalar(ultima.texto))
    }
}

// MARK: - Modo voz

private struct PalcoDeVoz: View {
    @Environment(Modelo.self) private var modelo
    @Bindable var ouvido: Ouvido
    let abrirDigitacao: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("CENTRAL").font(.system(size: 13, weight: .bold, design: .monospaced))
                Spacer()
                if !modelo.mensagens.isEmpty {
                    Button { modelo.novaConversa() } label: {
                        Image(systemName: "square.and.pencil")
                    }
                    .buttonStyle(.borderless)
                    .disabled(modelo.conversando)
                    .help("Nova conversa")
                    .accessibilityLabel("Nova conversa")
                }
            }
            .padding(12)

            Spacer(minLength: 12)
            ZStack {
                if ouvindo {
                    Circle()
                        .fill(Paleta.noah.opacity(0.10 + ouvido.nivel * 0.25))
                        .frame(width: 210, height: 210)
                        .scaleEffect(1 + ouvido.nivel * 0.25)
                        .blur(radius: 18)
                }
                Rosto(estado: estadoRosto, tamanho: 140)
                    .scaleEffect(1 + ouvido.nivel * 0.12)
            }
            .animation(.easeOut(duration: 0.12), value: ouvido.nivel)
            .frame(height: 220)

            Text(status)
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
                .foregroundStyle(corDoStatus)
                .multilineTextAlignment(.center)
                .padding(.top, 6)
            Text(legenda)
                .font(.system(size: 15))
                .foregroundStyle(ouvido.parcial.isEmpty ? .secondary : .primary)
                .multilineTextAlignment(.center)
                .lineLimit(4)
                .padding(.horizontal, 24).padding(.top, 8)
                .frame(minHeight: 60, alignment: .top)
                .textSelection(.enabled)
            Spacer(minLength: 12)

            HStack {
                Botao(icone: ouvido.mudo ? "mic.slash.fill" : "mic.fill",
                      ativo: !ouvido.mudo,
                      rotulo: ouvido.mudo ? "Ligar microfone" : "Deixar mudo") {
                    ouvido.mudo.toggle()
                }
                Spacer()
                Button(action: abrirDigitacao) {
                    VStack(spacing: 2) {
                        Image(systemName: "chevron.up").font(.system(size: 18, weight: .semibold))
                        Text("digitar").font(.system(size: 10, design: .monospaced))
                    }
                    .foregroundStyle(.secondary)
                    .frame(width: 70, height: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Abrir o chat para digitar")
                Spacer()
                Botao(icone: ouvido.falarRespostas ? "speaker.wave.2.fill" : "speaker.slash.fill",
                      ativo: ouvido.falarRespostas,
                      rotulo: ouvido.falarRespostas ? "Não ler as respostas" : "Ler as respostas em voz alta") {
                    ouvido.falarRespostas.toggle()
                    if !ouvido.falarRespostas { ouvido.calar() }
                }
            }
            .padding(.horizontal, 16).padding(.bottom, 12)
        }
    }

    private var ouvindo: Bool { ouvido.estado == .ouvindo }

    private var estadoRosto: EstadoIlha {
        if modelo.conversando { return .trabalhando }
        if ouvido.falando { return .pronto }
        return .quieto
    }

    private var status: String {
        if modelo.conversando { return "Noah pensando…" }
        if ouvido.falando { return "Noah falando…" }
        switch ouvido.estado {
        case .semPermissao(let m), .indisponivel(let m): return m
        case .ouvindo: return "Estou ouvindo…"
        case .desligado: return ouvido.mudo ? "Microfone mudo" : "Ligando o microfone…"
        }
    }

    private var corDoStatus: Color {
        switch ouvido.estado {
        case .semPermissao, .indisponivel: .orange
        default: Paleta.noah
        }
    }

    /// O que você está falando agora; senão, a última coisa da conversa.
    private var legenda: String {
        if !ouvido.parcial.isEmpty { return ouvido.parcial }
        guard let ultima = modelo.mensagens.last else { return "Fale com o Noah. Uma pausa envia a frase." }
        switch ultima.autor {
        case .eu: return "Você: \(ultima.texto)"
        case .noah: return FalaDoNoah.paraFalar(ultima.texto, limite: 240)
        case .erro: return "Não deu: \(ultima.texto)"
        }
    }
}

private struct Botao: View {
    let icone: String
    let ativo: Bool
    let rotulo: String
    let acao: () -> Void

    var body: some View {
        Button(action: acao) {
            Image(systemName: icone)
                .font(.system(size: 18))
                .foregroundStyle(ativo ? Paleta.noah : Color.secondary)
                .frame(width: 44, height: 44)
                .background(Color.white.opacity(ativo ? 0.08 : 0.04), in: Circle())
        }
        .buttonStyle(.plain)
        .help(rotulo)
        .accessibilityLabel(rotulo)
    }
}

// MARK: - Modo digitação

private struct ChatDigitado: View {
    @Environment(Modelo.self) private var modelo
    @Bindable var ouvido: Ouvido
    let voltarParaVoz: () -> Void
    @State private var texto = ""
    @FocusState private var focado: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Rosto(estado: modelo.conversando ? .trabalhando : .quieto, tamanho: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text("CENTRAL").font(.system(size: 13, weight: .bold, design: .monospaced))
                    Text("as IAs conversando · fale com o Noah")
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                }
                Spacer()
                if !modelo.mensagens.isEmpty {
                    Button { modelo.novaConversa() } label: {
                        Label("nova conversa", systemImage: "square.and.pencil")
                            .font(.system(size: 11, design: .monospaced))
                    }
                    .buttonStyle(.bordered)
                    .disabled(modelo.conversando)
                }
                Button(action: voltarParaVoz) {
                    Image(systemName: "chevron.down").font(.system(size: 15, weight: .semibold))
                        .frame(width: 30, height: 30)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .help("Voltar a falar com o Noah")
                .accessibilityLabel("Voltar a falar com o Noah")
            }
            .padding(12)
            Divider()

            ScrollViewReader { leitor in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if modelo.mensagens.isEmpty {
                            Vazio()
                        }
                        ForEach(modelo.mensagens) { Balao(m: $0).id($0.id) }
                        if modelo.conversando {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text("Noah pensando…").font(.system(size: 12, design: .monospaced))
                                    .foregroundStyle(Paleta.noah)
                            }
                            .id("pensando")
                        }
                    }
                    .padding(12)
                }
                .onAppear { leitor.scrollTo(modelo.mensagens.last?.id, anchor: .bottom) }
                .onChange(of: modelo.mensagens.count) {
                    withAnimation { leitor.scrollTo(modelo.mensagens.last?.id, anchor: .bottom) }
                }
                .onChange(of: modelo.conversando) { _, v in
                    if v { withAnimation { leitor.scrollTo("pensando", anchor: .bottom) } }
                }
            }

            Divider()
            HStack(spacing: 8) {
                TextField("Mensagem para o Noah", text: $texto, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.plain)
                    .font(.system(size: 14))
                    .focused($focado)
                    .onSubmit(enviar)
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
                Button(action: enviar) {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 26))
                        .foregroundStyle(podeEnviar ? Paleta.noah : Color.secondary)
                }
                .buttonStyle(.plain)
                .disabled(!podeEnviar)
                .keyboardShortcut(.return, modifiers: .command)
                .accessibilityLabel("Enviar ao Noah")
            }
            .padding(10)
        }
        .onAppear { focado = true }
    }

    private var podeEnviar: Bool {
        !modelo.conversando && !texto.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func enviar() {
        guard podeEnviar else { return }
        let t = texto
        texto = ""
        Task { await modelo.conversar(t) }
    }
}
