import NoahCore
import SwiftUI

/// Aba Central: conversa com o Noah (via `POST /central/api/conversa`) ao lado
/// do que a central sabe das IAs — quem falou com quem, os modelos, as pastas
/// do Cérebro. Tudo de `GET /central/api/atividade`; nada aqui é inventado.
struct CentralView: View {
    @Environment(Modelo.self) private var modelo

    var body: some View {
        GeometryReader { geo in
            let largo = geo.size.width >= 760
            Group {
                if largo {
                    HStack(alignment: .top, spacing: 14) {
                        ConversaVoz().frame(maxWidth: .infinity)
                        ScrollView { Paineis().padding(.bottom, 16) }
                            .frame(width: min(geo.size.width * 0.42, 460))
                    }
                    .padding(12)
                } else {
                    ScrollView {
                        VStack(spacing: 14) {
                            ConversaVoz().frame(height: max(geo.size.height * 0.62, 380))
                            Paineis()
                        }
                        .padding(12)
                    }
                    .refreshable { await modelo.atualizarPainel() }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .background(Paleta.fundo.ignoresSafeArea())
        .environment(\.colorScheme, .dark)
        .task {
            // Enquanto a aba está aberta, o feed segue vivo.
            while !Task.isCancelled {
                await modelo.atualizarPainel()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }
}

// MARK: - Conversa com o Noah (a tela fica em ConversaVoz.swift)

struct Vazio: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Converse com o Noah por aqui.")
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
            Text("A mensagem vai para a central no Mac, que roda o Noah com o modelo local e devolve a resposta e as ferramentas que ele usou. Uma de cada vez.")
                .font(.system(size: 12)).foregroundStyle(.secondary)
        }
        .padding(.vertical, 8)
    }
}

struct Balao: View {
    let m: MensagemChat

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if m.autor == .eu { Spacer(minLength: 40) }
            if m.autor == .noah { Rosto(estado: .pronto, tamanho: 22) }
            VStack(alignment: m.autor == .eu ? .trailing : .leading, spacing: 5) {
                Text(m.autor == .erro ? "Não deu: \(m.texto)" : m.texto)
                    .font(.system(size: 14))
                    .textSelection(.enabled)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(fundo, in: RoundedRectangle(cornerRadius: 14))
                if !m.ferramentas.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "wrench.and.screwdriver").font(.system(size: 9))
                        ForEach(m.ferramentas, id: \.self) { f in
                            Text(f).font(.system(size: 10, design: .monospaced))
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(Paleta.noah.opacity(0.18), in: Capsule())
                        }
                    }
                    .foregroundStyle(Paleta.noah)
                }
            }
            if m.autor != .eu { Spacer(minLength: 40) }
        }
    }

    private var fundo: Color {
        switch m.autor {
        case .eu: Paleta.central.opacity(0.35)
        case .noah: Paleta.noah.opacity(0.18)
        case .erro: Color.red.opacity(0.25)
        }
    }
}

// MARK: - Painéis: feed, modelos, Cérebro

private struct Paineis: View {
    @Environment(Modelo.self) private var modelo

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let erro = modelo.erroPainel {
                Aviso(texto: "Central sem resposta: \(erro)", cor: .orange)
            }
            if let painel = modelo.painel {
                if !painel.ollama {
                    Aviso(texto: "Ollama fora do ar: os Qwen locais e o Noah não respondem.", cor: .orange)
                }
                ForEach(painel.falhas, id: \.self) { Aviso(texto: $0, cor: .yellow) }
                Feed(painel: painel)
                Modelos(painel: painel)
                Pastas(pastas: painel.cerebro.pastas)
            } else if modelo.erroPainel == nil {
                ProgressView().frame(maxWidth: .infinity).padding()
            }
        }
    }
}

private struct Secao<Conteudo: View>: View {
    let titulo: String
    @ViewBuilder let conteudo: Conteudo

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(titulo.uppercased())
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(.secondary)
            conteudo
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 12))
    }
}

private struct Aviso: View {
    let texto: String
    let cor: Color
    var body: some View {
        Label(texto, systemImage: "exclamationmark.triangle.fill")
            .font(.system(size: 12))
            .foregroundStyle(cor)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(cor.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
    }
}

private struct Feed: View {
    let painel: PainelCentral

    var body: some View {
        Secao(titulo: "Quem falou com quem") {
            if painel.eventos.isEmpty {
                Text("Nada registrado ainda.").font(.system(size: 12)).foregroundStyle(.secondary)
            }
            ForEach(painel.eventos.prefix(30)) { e in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 4) {
                        Text(Nomes.de(e.de, painel)).foregroundStyle(Paleta.cor(id: e.de))
                        Image(systemName: "arrow.right").font(.system(size: 9)).foregroundStyle(.secondary)
                        Text(Nomes.de(e.para, painel)).foregroundStyle(Paleta.cor(id: e.para))
                        Spacer()
                        Text(Sincronia.haQuanto(Date(timeIntervalSince1970: e.quando)))
                            .foregroundStyle(.secondary)
                    }
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    if !e.texto.isEmpty {
                        Text(e.texto).font(.system(size: 12)).lineLimit(2).foregroundStyle(.primary.opacity(0.85))
                    }
                }
                .padding(.vertical, 3)
            }
        }
    }
}

private struct Modelos: View {
    let painel: PainelCentral

    var body: some View {
        Secao(titulo: "Modelos") {
            ForEach(painel.modelos) { m in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Circle().fill(cor(m)).frame(width: 7, height: 7)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(m.nome).font(.system(size: 12, weight: .semibold, design: .monospaced))
                        Text(detalhe(m)).font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("\(m.usos24h) em 24 h").font(.system(size: 11, design: .monospaced))
                        if let u = m.ultimoUso {
                            Text(Sincronia.haQuanto(Date(timeIntervalSince1970: u)))
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private func cor(_ m: ModeloAuxiliar) -> Color {
        switch m.disponivel {
        case true?: m.carregado ? Paleta.verde : Paleta.modelo
        case false?: .red
        case nil: .gray
        }
    }

    private func detalhe(_ m: ModeloAuxiliar) -> String {
        var partes = [m.provedor]
        if m.disponivel == false { partes.append("indisponível") }
        if m.carregado { partes.append("na memória") }
        if m.id == painel.noah?.modelo { partes.append("do Noah") }
        if !m.rotas.isEmpty { partes.append("rotas: " + m.rotas.joined(separator: ", ")) }
        return partes.joined(separator: " · ")
    }
}

private struct Pastas: View {
    let pastas: [PastaCerebro]

    var body: some View {
        Secao(titulo: "Cérebro") {
            if pastas.isEmpty {
                Text("Pastas não encontradas.").font(.system(size: 12)).foregroundStyle(.secondary)
            }
            ForEach(pastas) { p in
                HStack(spacing: 6) {
                    Text(p.numero).font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundStyle(Paleta.cerebro)
                    Text(p.nome).font(.system(size: 12)).lineLimit(1)
                    Spacer()
                    Text("\(p.notas)").font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                }
            }
        }
    }
}

/// Nomes legíveis para o `de`/`para` do feed.
enum Nomes {
    static func de(_ id: String, _ painel: PainelCentral) -> String {
        switch id {
        case "agente": "Claude/Codex"
        case Fluxo.claude: "Claude"
        case Fluxo.codex: "Codex"
        case Fluxo.noah: "Noah"
        case Fluxo.cerebro: "Cérebro"
        case Fluxo.central: "Central"
        case Fluxo.aparelhos, "app": "App"
        default:
            if let m = painel.modelos.first(where: { $0.id == id }), !m.local { m.nome } else { id }
        }
    }
}
