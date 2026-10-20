import Foundation
import NoahCore
import Observation
import UserNotifications

enum Aba: Hashable { case pendencias, fluxo, presenca, ajustes }

/// Estado do app. Atualiza sozinho no mesmo ritmo do PWA (20 s; 4 s enquanto
/// alguém responde; 10 s com a aba Fluxo aberta) e repassa a lista aos avisos.
@MainActor @Observable
final class Modelo {
    var itens: [Pendencia] = []
    var jobs: [Job] = []
    var falhas: [String] = []
    var erro: String?
    var presenca: EstadoPresenca?
    var erroPresenca: String?
    /// Sinal ao vivo do Cérebro para a aba Fluxo; nil numa central sem a rota.
    var cerebro: SinalCerebro?
    var aviso: String?
    var rascunhos: [String: String] = [:]
    var enviando: Set<String> = []
    var aba: Aba = .pendencias
    var atualizadoEm: Date?
    var permissao: UNAuthorizationStatusTexto = .desconhecida
    /// Feed do painel "Ao vivo": o que mudou desde que o app abriu.
    var atividade: [Evento] = []
    /// Pendência aberta no detalhe (a chave, para seguir a lista viva).
    var selecionada: String?

    private var lido = false
    private var laco: Task<Void, Never>?
    private var sono: Task<Void, Never>?

    var jobsVisiveis: [Job] { Sincronia.jobsVisiveis(jobs) }
    var contagem: Int { itens.filter { !$0.respondendo }.count }
    func item(_ chave: String) -> Pendencia? { itens.first { $0.chave == chave } }

    init() {
        Avisos.shared.aoAgir = { [weak self] in await self?.atualizar() }
        Avisos.shared.aoAbrir = { [weak self] chave in self?.abrir(chave) }
    }

    func iniciar() {
        guard laco == nil else { return }
        laco = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.atualizar()
                await self.esperar(Sincronia.proximoIntervalo(self.jobs, vendoFluxo: self.aba == .fluxo))
            }
        }
    }

    func parar() {
        laco?.cancel()
        laco = nil
        sono?.cancel()
    }

    /// Dorme até o próximo ciclo; `cutucar()` acorda antes.
    private func esperar(_ segundos: TimeInterval) async {
        let t = Task<Void, Never> { try? await Task.sleep(for: .seconds(segundos)) }
        sono = t
        await t.value
    }

    func cutucar() { sono?.cancel() }

    func atualizar() async {
        do {
            let cliente = try Ajustes.cliente()
            let r = try await cliente.pendencias()
            let novos = Atividade.eventos(anteriores: lido ? itens : nil, atuais: r.itens,
                                          jobsAnteriores: jobs, jobsAtuais: r.respondendo)
            atividade = Atividade.juntar(novos, em: atividade)
            lido = true
            itens = r.itens
            jobs = r.respondendo
            falhas = r.falhas
            erro = nil
            atualizadoEm = Date()
            await Avisos.shared.sincronizar(r.itens)
        } catch {
            self.erro = error.localizedDescription
        }
        // A permissão pode mudar fora do app (Ajustes do sistema): relê a cada ciclo.
        await lerPermissao()
        if aba == .presenca { await atualizarPresenca() }
        if aba == .fluxo { await atualizarCerebro() }
    }

    func lerPermissao() async {
        permissao = .init(await Avisos.shared.estado())
    }

    func pedirPermissao() async {
        await Avisos.shared.pedirPermissao()
        await lerPermissao()
    }

    func atualizarPresenca() async {
        do {
            presenca = try await Ajustes.cliente().presenca()
            erroPresenca = nil
        } catch {
            erroPresenca = error.localizedDescription
        }
    }

    /// Falha de rede deixa o mapa sem sinal (nil) em vez de mostrar contagem velha.
    func atualizarCerebro() async {
        cerebro = try? await Ajustes.cliente().cerebro()
    }

    func responder(_ p: Pendencia, texto: String) async {
        enviando.insert(p.chave)
        defer { enviando.remove(p.chave) }
        do {
            try await Ajustes.cliente().responder(p, texto: texto)
            rascunhos[p.chave] = nil
            mostrar("Enviado. \(Fonte.nome(p.fonte)) está respondendo.")
        } catch {
            mostrar(error.localizedDescription)
        }
        await atualizar()
    }

    func aceitar(_ p: Pendencia) async {
        await responder(p, texto: Ajustes.respostaAceitar)
    }

    func dispensar(_ p: Pendencia) async {
        enviando.insert(p.chave)
        defer { enviando.remove(p.chave) }
        do {
            try await Ajustes.cliente().dispensar(p)
            itens.removeAll { $0.chave == p.chave }
            if selecionada == p.chave { selecionada = nil }
        } catch {
            mostrar(error.localizedDescription)
        }
        await atualizar()
    }

    /// Leva ao detalhe de uma pendência (toque no aviso ou na barra de menus).
    func abrir(_ chave: String) {
        aba = .pendencias
        selecionada = chave
    }

    func mostrar(_ texto: String) {
        aviso = texto
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            if self?.aviso == texto { self?.aviso = nil }
        }
    }
}
