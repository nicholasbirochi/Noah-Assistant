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
        }
        .defaultSize(width: 1100, height: 720)

        // Fica na barra de menus mesmo com a janela fechada, para continuar avisando.
        MenuBarExtra {
            MenuDaBarra().environment(modelo)
        } label: {
            Image(systemName: modelo.contagem > 0 ? "bell.badge.fill" : "bell")
            if modelo.contagem > 0 { Text("\(modelo.contagem)") }
        }
        #else
        WindowGroup {
            ContentView()
                .environment(modelo)
                .task { await modelo.pedirPermissao() }
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
}

struct MenuDaBarra: View {
    @Environment(Modelo.self) private var modelo
    @Environment(\.openWindow) private var abrirJanela

    var body: some View {
        if modelo.itens.isEmpty {
            Text("Nada esperando você")
        }
        ForEach(modelo.itens.prefix(10)) { p in
            Button("\(Fonte.nome(p.fonte)): \(p.tarefa)") {
                modelo.abrir(p.chave)
                abrir()
            }
        }
        Divider()
        Button("Abrir Noah") { abrir() }.keyboardShortcut("o")
        Button("Atualizar") { Task { await modelo.atualizar() } }.keyboardShortcut("r")
        Divider()
        Button("Sair do Noah") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }

    private func abrir() {
        abrirJanela(id: "principal")
        NSApp.activate()
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
    }
}
#endif
