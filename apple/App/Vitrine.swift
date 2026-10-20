import Foundation
import NoahCore
#if os(iOS)
import ActivityKit
import WidgetKit
#endif

/// Leva o resumo da central para fora do app: widgets (via App Group) e a
/// Live Activity da ilha dinâmica. No Mac só serve à barra de menus.
@MainActor
enum Vitrine {
    private static var ultimo: ResumoIlha?

    static func publicar(_ r: ResumoIlha) async {
        #if os(iOS)
        let mudou = !(ultimo?.mesmoConteudo(r) ?? false)
        ultimo = r
        if mudou, let grupo = UserDefaults(suiteName: Ilha.grupo) {
            Ilha.gravar(r, em: grupo)
            WidgetCenter.shared.reloadAllTimelines()
        }
        await atividade(r, mudou: mudou)
        #endif
    }

    #if os(iOS)
    /// Uma Live Activity só: começa quando há algo a mostrar, muda junto com o
    /// resumo e some quando tudo fica calmo. Sem push (APNs), só muda enquanto o
    /// app roda ou quando o iOS o acorda em segundo plano.
    private static func atividade(_ r: ResumoIlha, mudou: Bool) async {
        let atuais = Activity<NoahAtributos>.activities
        let pode = Ajustes.ilhaLigada && ActivityAuthorizationInfo().areActivitiesEnabled
        // Se ficar sem notícias por 30 min, o sistema mostra a atividade como velha.
        let conteudo = ActivityContent(state: r, staleDate: Date(timeIntervalSinceNow: 30 * 60))
        guard pode, r.estado != .quieto else {
            for a in atuais { await a.end(conteudo, dismissalPolicy: .immediate) }
            return
        }
        if let a = atuais.first {
            if mudou || a.activityState == .stale { await a.update(conteudo) }
            for extra in atuais.dropFirst() { await extra.end(nil, dismissalPolicy: .immediate) }
        } else {
            // Só começa com o app em primeiro plano; em segundo plano o iOS recusa.
            _ = try? Activity.request(attributes: NoahAtributos(), content: conteudo, pushType: nil)
        }
    }

    static func encerrar() async {
        for a in Activity<NoahAtributos>.activities { await a.end(nil, dismissalPolicy: .immediate) }
    }
    #endif
}
