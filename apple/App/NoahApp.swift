import NoahCore
import SwiftUI
#if os(macOS)
import AppKit
#else
import BackgroundTasks
#endif

@main
struct NoahApp: App {
    #if os(macOS)
    @NSApplicationDelegateAdaptor(Delegado.self) private var delegado
    #endif
    @State private var modelo: Modelo
    @Environment(\.scenePhase) private var fase

    init() {
        Avisos.shared.configurar()
        let m = Modelo()
        _modelo = State(initialValue: m)
        m.iniciar()
        #if os(macOS)
        IlhaMac.shared.modelo = m
        #endif
    }

    var body: some Scene {
        #if os(macOS)
        WindowGroup("Noah", id: "principal") {
            ContentView()
                .environment(modelo)
                // Lista + detalhe + painel "Ao vivo" lado a lado: abaixo disso o
                // AppKit entra em laço de layout e derruba o app.
                .frame(minWidth: 860, minHeight: 520)
                // Pede depois que a janela existe; o pedido não segura a lista.
                .task { await modelo.pedirPermissao() }
                .onOpenURL { modelo.ir($0) }
        }
        .defaultSize(width: 1100, height: 720)
        .handlesExternalEvents(matching: [Atalho.esquema])

        // Fica na barra de menus mesmo com a janela fechada, para continuar avisando.
        // Estilo janela: um painel com o rosto do Noah, como a ilha do iPhone.
        MenuBarExtra {
            PainelDaBarra().environment(modelo)
        } label: {
            let r = modelo.resumo
            Image(systemName: r.estado.simbolo)
            if r.esperando > 0 { Text("\(r.esperando)") }
        }
        .menuBarExtraStyle(.window)
        #else
        WindowGroup {
            ContentView()
                .environment(modelo)
                .task { await modelo.pedirPermissao() }
                .onOpenURL { modelo.ir($0) }
        }
        .onChange(of: fase) { _, nova in
            switch nova {
            case .active:
                modelo.iniciar()
            case .background:
                modelo.parar()
                Fundo.agendar()
            default:
                break
            }
        }
        .backgroundTask(.appRefresh(Fundo.identificador)) {
            await Fundo.atualizar()
        }
        #endif
    }
}

#if os(macOS)
final class Delegado: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationDidFinishLaunching(_ notification: Notification) {
        MainActor.assumeIsolated { IlhaMac.shared.aplicar() }
    }
}

/// Painel da barra de menus: estado no mesmo código de cores da ilha, as
/// pendências com Aceitar (pede Touch ID) e um atalho para o app de cada agente.
struct PainelDaBarra: View {
    @Environment(Modelo.self) private var modelo
    @Environment(\.openWindow) private var abrirJanela

    var body: some View {
        let r = modelo.resumo
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Rosto(estado: r.estado, tamanho: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(r.estado.titulo).font(.headline).foregroundStyle(r.estado.cor)
                    Text(r.linha).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Button { Task { await modelo.atualizar() } } label: { Image(systemName: "arrow.clockwise") }
                    .buttonStyle(.borderless).help("Atualizar").keyboardShortcut("r")
            }
            Divider()
            if modelo.itens.isEmpty {
                Text("Nada esperando você").foregroundStyle(.secondary).padding(.vertical, 6)
            } else {
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(modelo.itens.prefix(8)) { p in linha(p) }
                    }
                }
                .frame(maxHeight: 320)
            }
            Divider()
            HStack {
                Button("Abrir Noah") { abrir() }.keyboardShortcut("o")
                Spacer()
                Button("Sair") { NSApp.terminate(nil) }.keyboardShortcut("q")
            }
            .buttonStyle(.borderless)
        }
        .padding(12)
        .frame(width: 340)
    }

    private func linha(_ p: Pendencia) -> some View {
        let ocupado = p.respondendo || modelo.enviando.contains(p.chave)
        return HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                Text(Fonte.nome(p.fonte)).font(.caption2.bold()).foregroundStyle(.secondary)
                Text(p.tarefa).font(.callout).lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture { modelo.abrir(p.chave); abrir() }
            if let app = Fonte.app(p.fonte) {
                Button { abrirApp(app) } label: { Image(systemName: "arrow.up.forward.app") }
                    .buttonStyle(.borderless).help("Abrir no \(Fonte.nome(p.fonte))")
            }
            if !p.automatica && p.simples && p.podeResponder {
                Button(ocupado ? "…" : "Aceitar") { Task { await modelo.aceitar(p) } }
                    .controlSize(.small).disabled(ocupado)
                    .help("Pede Touch ID antes de enviar")
            }
        }
        .padding(8)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }

    private func abrir() {
        abrirJanela(id: "principal")
        NSApp.activate()
    }

    /// Só abre o app do agente; fechar ou apagar outro app não cabe aqui.
    private func abrirApp(_ identificador: String) {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: identificador) else {
            return modelo.mostrar("App não encontrado neste Mac.")
        }
        NSWorkspace.shared.openApplication(at: url, configuration: .init())
    }
}
#else
/// Sem conta paga da Apple não há push (APNs): com o app fechado, o iOS acorda
/// o app de tempos em tempos (ele decide quando) para buscar e avisar.
enum Fundo {
    static let identificador = "com.nicholasbirochi.noah.atualizar"

    static func agendar() {
        let pedido = BGAppRefreshTaskRequest(identifier: identificador)
        pedido.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(pedido)
    }

    @MainActor
    static func atualizar() async {
        agendar()
        guard let cliente = try? Ajustes.cliente(),
              let r = try? await cliente.pendencias() else { return }
        await Avisos.shared.sincronizar(r.itens)
        await Vitrine.publicar(Ilha.resumo(itens: r.itens, jobs: r.respondendo))
    }
}
#endif
