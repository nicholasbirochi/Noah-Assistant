import Foundation
import NoahCore
import Observation
import UserNotifications

enum Aba: Hashable { case pendencias, fluxo, central, presenca, ajustes }

/// Uma fala da conversa com o Noah na aba Central.
struct MensagemChat: Identifiable, Equatable {
    enum Autor { case eu, noah, erro }
    let id = UUID()
    let autor: Autor
    let texto: String
    var ferramentas: [String] = []
    let quando = Date()
}

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
    /// Sinal por agente e por parte do Cérebro; nil quando a rota não existe ou falha.
    var cerebro: SinalCerebro?
    /// Modelos, pastas do Cérebro e feed da central (abas Fluxo e Central).
    var painel: PainelCentral?
    var erroPainel: String?
    /// Conversa com o Noah na aba Central; a sessão segue entre mensagens.
    var mensagens: [MensagemChat] = []
    var sessaoNoah: String?
    var conversando = false
    var aviso: String?
    var rascunhos: [String: String] = [:]
    var enviando: Set<String> = []
    /// Ao entrar no Fluxo ou na Central, acorda o laço para já passar a ler a cada 2 s.
    var aba: Aba = .pendencias { didSet { if aba != oldValue { cutucar() } } }
    var atualizadoEm: Date?
    var permissao: UNAuthorizationStatusTexto = .desconhecida
    /// Feed do painel "Ao vivo": o que mudou desde que o app abriu.
    var atividade: [Evento] = []
    /// Pendência aberta no detalhe (a chave, para seguir a lista viva).
    var selecionada: String?

    private var lido = false
    private var laco: Task<Void, Never>?
    private var sono: Task<Void, Never>?
    /// Só a conversa mais recente pode atualizar a tela. Guardamos a Task da
    /// rede para que uma fala nova cancele também a espera HTTP local.
    private var requestConversa: UUID?
    private var tarefaConversa: Task<RespostaConversa, Error>?

    var jobsVisiveis: [Job] { Sincronia.jobsVisiveis(jobs) }
    /// O que a ilha, os widgets e a barra de menus mostram.
    var resumo: ResumoIlha { Ilha.resumo(itens: itens, jobs: jobs) }
    /// Selo da aba: só o que pede algo a você (respostas prontas ficam de fora).
    var contagem: Int { itens.filter { !$0.respondendo && $0.pergunta }.count }
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
                await self.esperar(Sincronia.proximoIntervalo(self.jobs, aoVivo: self.aba == .fluxo || self.aba == .central))
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
            await Vitrine.publicar(resumo)
        } catch {
            self.erro = error.localizedDescription
        }
        // A permissão pode mudar fora do app (Ajustes do sistema): relê a cada ciclo.
        await lerPermissao()
        if aba == .presenca { await atualizarPresenca() }
        if aba == .fluxo || aba == .central {
            await atualizarCerebro()
            await atualizarPainel()
        }
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

    func atualizarPainel() async {
        do {
            painel = try await Ajustes.cliente().atividade()
            erroPainel = nil
        } catch {
            erroPainel = error.localizedDescription
        }
    }

    /// Manda uma mensagem ao Noah pela central. Uma fala nova substitui o
    /// turno em andamento e cancela só o request anterior.
    func conversar(_ texto: String) async {
        let texto = texto.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !texto.isEmpty else { return }
        if let anterior = requestConversa {
            tarefaConversa?.cancel()
            let cliente = try? Ajustes.cliente()
            Task { try? await cliente?.cancelarConversa(requestID: anterior) }
        }
        let requestID = UUID()
        mensagens.append(MensagemChat(autor: .eu, texto: texto))
        requestConversa = requestID
        conversando = true
        // Lê o painel logo, para o Fluxo e o feed mostrarem o Noah pensando.
        let leitura = Task { [weak self] in
            try? await Task.sleep(for: .seconds(1))
            guard !Task.isCancelled else { return }
            await self?.atualizarPainel()
        }
        do {
            let cliente = try Ajustes.cliente()
            let chamada = Task { try await cliente.conversar(texto: texto, sessao: sessaoNoah, requestID: requestID) }
            tarefaConversa = chamada
            let r = try await chamada.value
            guard requestConversa == requestID else { leitura.cancel(); return }
            sessaoNoah = r.sessao
            mensagens.append(MensagemChat(autor: .noah, texto: r.resposta, ferramentas: r.ferramentas))
        } catch {
            guard requestConversa == requestID else { leitura.cancel(); return }
            mensagens.append(MensagemChat(autor: .erro, texto: error.localizedDescription))
        }
        leitura.cancel()
        guard requestConversa == requestID else { return }
        requestConversa = nil
        tarefaConversa = nil
        conversando = false
        await atualizarPainel()
    }

    /// Interrompe ao reconhecer o começo de uma fala nova, sem apagar o
    /// histórico nem a sessão da conversa.
    func interromperConversa() {
        guard let requestID = requestConversa else { return }
        requestConversa = nil
        tarefaConversa?.cancel()
        tarefaConversa = nil
        conversando = false
        let cliente = try? Ajustes.cliente()
        Task { try? await cliente?.cancelarConversa(requestID: requestID) }
        Task { await atualizarPainel() }
    }

    func novaConversa() {
        mensagens = []
        sessaoNoah = nil
    }

    func responder(_ p: Pendencia, texto: String) async {
        await responder(p, texto: texto, motivo: "Enviar a resposta para \(Fonte.nome(p.fonte))")
    }

    private func responder(_ p: Pendencia, texto: String, motivo: String) async {
        guard await Cadeado.confirmar(motivo) else { return mostrar("Não confirmado. Nada foi enviado.") }
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
        await responder(p, texto: Ajustes.respostaAceitar, motivo: "Aceitar o pedido de \(Fonte.nome(p.fonte))")
    }

    func dispensar(_ p: Pendencia) async {
        guard await Cadeado.confirmar("Dispensar a pendência de \(Fonte.nome(p.fonte))") else {
            return mostrar("Não confirmado. A pendência continua.")
        }
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

    /// Links `noah://` da ilha, dos widgets e da barra de menus.
    func ir(_ url: URL) {
        switch Atalho.destino(url) {
        case .pendencia(let chave): abrir(chave)
        case .lista: aba = .pendencias
        case .fluxo: aba = .fluxo
        case nil: break
        }
    }

    func mostrar(_ texto: String) {
        aviso = texto
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            if self?.aviso == texto { self?.aviso = nil }
        }
    }
}
