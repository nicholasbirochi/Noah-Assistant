import Foundation
import NoahCore
import UserNotifications

/// Avisos com ação: cada aparelho avisa as pendências novas e deixa responder,
/// aceitar ou dispensar direto do aviso. A sincronia entre Mac e iPhone vem da
/// central: o que um aparelho faz some da lista, e o outro apaga o aviso dele
/// na próxima atualização.
@MainActor
final class Avisos: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Avisos()

    static let categoria = "PENDENCIA"
    /// Pergunta aberta: Responder e Dispensar, sem Aceitar.
    static let categoriaEscrita = "PENDENCIA_ESCRITA"
    static let categoriaLeitura = "PENDENCIA_LEITURA"
    static let acaoResponder = "RESPONDER"
    static let acaoAceitar = "ACEITAR"
    static let acaoDispensar = "DISPENSAR"

    private let centro = UNUserNotificationCenter.current()
    private let chaveAvisados = "avisados"
    /// Chamado depois de uma ação vinda do aviso, para a lista refletir na hora.
    var aoAgir: (@MainActor () async -> Void)?
    /// Chamado quando tocam no aviso em si: abre o detalhe daquela pendência.
    var aoAbrir: (@MainActor (String) -> Void)?

    func configurar() {
        centro.delegate = self
        let responder = UNTextInputNotificationAction(
            identifier: Self.acaoResponder, title: "Responder", options: [.authenticationRequired],
            textInputButtonTitle: "Enviar", textInputPlaceholder: "Sua resposta")
        let aceitar = UNNotificationAction(identifier: Self.acaoAceitar, title: "Aceitar",
                                           options: [.authenticationRequired])
        let dispensar = UNNotificationAction(identifier: Self.acaoDispensar, title: "Dispensar",
                                             options: [.destructive, .authenticationRequired])
        centro.setNotificationCategories([
            UNNotificationCategory(identifier: Self.categoria, actions: [responder, aceitar, dispensar],
                                   intentIdentifiers: []),
            UNNotificationCategory(identifier: Self.categoriaEscrita, actions: [responder, dispensar],
                                   intentIdentifiers: []),
            UNNotificationCategory(identifier: Self.categoriaLeitura, actions: [dispensar],
                                   intentIdentifiers: []),
        ])
    }

    @discardableResult
    func pedirPermissao() async -> Bool {
        (try? await centro.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    func estado() async -> UNAuthorizationStatus {
        await centro.notificationSettings().authorizationStatus
    }

    // MARK: - Sincronia

    private var avisados: Avisados {
        get {
            guard let dado = UserDefaults.standard.data(forKey: chaveAvisados),
                  let salvo = try? JSONDecoder().decode(Avisados.self, from: dado) else { return Avisados() }
            return salvo
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: chaveAvisados) }
    }

    /// Compara com o que este aparelho já avisou: avisa as novas (ou que mudaram),
    /// apaga o aviso das que sumiram ou que alguém já está respondendo.
    func sincronizar(_ itens: [Pendencia]) async {
        let (mudanca, novo) = Sincronia.comparar(avisados, com: itens)
        avisados = novo
        let apagar = mudanca.sumidas + itens.filter(\.respondendo).map(\.chave)
        if !apagar.isEmpty {
            centro.removeDeliveredNotifications(withIdentifiers: apagar)
            centro.removePendingNotificationRequests(withIdentifiers: apagar)
        }
        try? await centro.setBadgeCount(itens.filter { !$0.respondendo }.count)
        let permissao = await estado()
        guard permissao == .authorized || permissao == .provisional else { return }
        for p in mudanca.novas {
            try? await centro.add(Self.pedido(p))
        }
    }

    static func pedido(_ p: Pendencia) -> UNNotificationRequest {
        let c = UNMutableNotificationContent()
        c.title = "\(Fonte.nome(p.fonte)): \(p.titulo)"
        if !p.projeto.isEmpty { c.subtitle = p.projeto }
        c.body = p.mensagem.isEmpty ? "Esperando você." : p.mensagem
        c.sound = .default
        c.threadIdentifier = p.fonte
        c.categoryIdentifier = !p.podeResponder ? categoriaLeitura : (p.simples ? categoria : categoriaEscrita)
        c.userInfo = ["fonte": p.fonte, "ident": p.ident, "chave": p.chave, "titulo": p.titulo]
        // A chave é a mesma nos dois aparelhos: o aviso novo substitui o antigo.
        return UNNotificationRequest(identifier: p.chave, content: c, trigger: nil)
    }

    private func falhou(_ titulo: String, _ erro: Error) async {
        let c = UNMutableNotificationContent()
        c.title = "Não deu: \(titulo)"
        c.body = erro.localizedDescription
        c.sound = .default
        try? await centro.add(UNNotificationRequest(identifier: "falha-\(UUID().uuidString)", content: c, trigger: nil))
    }

    // MARK: - Ações no aviso

    func agir(acao: String, info: [AnyHashable: Any], texto: String?) async {
        guard let fonte = info["fonte"] as? String, let ident = info["ident"] as? String else { return }
        let titulo = info["titulo"] as? String ?? ""
        let p = Pendencia(fonte: fonte, ident: ident, titulo: titulo, chave: info["chave"] as? String)
        do {
            let cliente = try Ajustes.cliente()
            switch acao {
            case Self.acaoResponder:
                try await cliente.responder(p, texto: texto ?? "")
            case Self.acaoAceitar:
                try await cliente.responder(p, texto: Ajustes.respostaAceitar)
            case Self.acaoDispensar:
                try await cliente.dispensar(p)
            case UNNotificationDefaultActionIdentifier:
                aoAbrir?(p.chave)
            default:
                return
            }
        } catch {
            await falhou(titulo.isEmpty ? Fonte.nome(fonte) : titulo, error)
        }
        await aoAgir?()
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification)
        async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            didReceive response: UNNotificationResponse) async {
        let acao = response.actionIdentifier
        let info = response.notification.request.content.userInfo
        let texto = (response as? UNTextInputNotificationResponse)?.userText
        await agir(acao: acao, info: info, texto: texto)
    }
}
