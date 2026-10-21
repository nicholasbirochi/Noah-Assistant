import XCTest
@testable import NoahCore

final class FluxoTests: XCTestCase {
    let agora: Double = 1_000_000

    func p(_ id: String, fonte: String = "claude", respondendo: Bool = false) -> Pendencia {
        var item = Pendencia(fonte: fonte, ident: id, titulo: id)
        item.respondendo = respondendo
        return item
    }
    func job(_ id: String, _ estado: String, fonte: String = "claude") -> Job {
        Job(id: id, chave: "\(fonte):\(id)", titulo: id, fonte: fonte, estado: estado, inicio: 0)
    }
    func painel(modelos: [ModeloAuxiliar] = [], pastas: [PastaCerebro] = [], eventos: [EventoCentral] = [],
                noah: EstadoNoah? = EstadoNoah()) -> PainelCentral {
        PainelCentral(modelos: modelos, pastas: pastas, eventos: eventos, noah: noah, geradoEm: agora)
    }

    func testSemDadosNadaFicaVivo() {
        let g = Fluxo.grafo(itens: [], jobs: [])
        XCTAssertFalse(g.ligacoes.contains { $0.estado == .viva })
        XCTAssertEqual(g.ligacao(Fluxo.claude, Fluxo.central)?.rotulo, "nada esperando")
        XCTAssertEqual(Set(g.ligacoes.map(\.id)).count, g.ligacoes.count)
        XCTAssertEqual(Set(g.nos.map(\.id)).count, g.nos.count)
        // Sem resposta da central ainda, os cinco modelos das rotas aparecem mesmo assim.
        XCTAssertEqual(g.nos.filter { $0.tipo == .modelo }.count, Fluxo.modelosPadrao.count)
        XCTAssertNotNil(g.ligacao(Fluxo.codex, Fluxo.modelo("nemotron")))
    }

    func testAgentesLigamDiretoNosModelosSemPassarPeloCerebro() {
        let g = Fluxo.grafo(itens: [], jobs: [], painel: painel(modelos: [
            ModeloAuxiliar(id: "qwen2.5-coder:14b", usos24h: 3, ultimoUso: agora - 60),
            ModeloAuxiliar(id: "qwen3-coder:30b", usos24h: 1, ultimoUso: agora - 4000),
            ModeloAuxiliar(id: "nemotron", nome: "Nemotron", provedor: "NVIDIA, gratuito", local: false),
            ModeloAuxiliar(id: "qwen2.5:7b", rotas: []),
        ]))
        let usado = g.ligacao(Fluxo.claude, Fluxo.modelo("qwen2.5-coder:14b"))
        XCTAssertEqual(usado?.estado, .viva)
        XCTAssertEqual(usado?.rotulo, "3 usos em 24 h")
        XCTAssertEqual(g.ligacao(Fluxo.codex, Fluxo.modelo("qwen2.5-coder:14b"))?.estado, .viva)
        XCTAssertEqual(g.ligacao(Fluxo.claude, Fluxo.modelo("qwen3-coder:30b"))?.estado, .parada)
        XCTAssertFalse(g.ligacoes.contains { $0.de == Fluxo.cerebro && $0.para.hasPrefix("modelo:") })
        XCTAssertEqual(g.no(Fluxo.modelo("nemotron"))?.detalhe, "NVIDIA grátis")
        XCTAssertEqual(g.no(Fluxo.modelo("qwen2.5-coder:14b"))?.nome, "qwen2.5-coder")
        // O modelo do Noah não tem rota: liga só no Noah.
        XCTAssertNil(g.ligacao(Fluxo.claude, Fluxo.modelo("qwen2.5:7b")))
        XCTAssertEqual(g.ligacao(Fluxo.noah, Fluxo.modelo("qwen2.5:7b"))?.estado, .parada)
    }

    func testNoahRespondendoAcendeConversa() {
        let g = Fluxo.grafo(itens: [], jobs: [], painel: painel(noah: EstadoNoah(respondendoDesde: agora - 2)))
        XCTAssertEqual(g.ligacao(Fluxo.noah, Fluxo.modelo("qwen2.5:7b"))?.estado, .viva)
        XCTAssertEqual(g.ligacao(Fluxo.central, Fluxo.noah)?.estado, .viva)
    }

    func testCerebroAbreNasPastas() {
        let pastas = [PastaCerebro(numero: "00", nome: "Regras", notas: 4),
                      PastaCerebro(numero: "02", nome: "Projetos", notas: 12, atualizadaEm: agora - 30)]
        let aberto = Fluxo.grafo(itens: [], jobs: [], painel: painel(pastas: pastas))
        XCTAssertEqual(aberto.no(Fluxo.pasta("02"))?.detalhe, "12 notas")
        XCTAssertEqual(aberto.ligacao(Fluxo.cerebro, Fluxo.pasta("02"))?.rotulo, "nota nova")
        XCTAssertEqual(aberto.ligacao(Fluxo.cerebro, Fluxo.pasta("00"))?.estado, .parada)

        let fechado = Fluxo.grafo(itens: [], jobs: [], painel: painel(pastas: pastas), cerebroAberto: false)
        XCTAssertFalse(fechado.nos.contains { $0.tipo == .pasta })
        XCTAssertEqual(fechado.no(Fluxo.cerebro)?.detalhe, "2 pastas · toque")
    }

    func testPastaAbertaMostraNotasESubpastas() {
        let pastas = [PastaCerebro(numero: "02", nome: "Projetos", notas: 2, atualizadaEm: agora - 30, itens: [
            .nota("Projeto - Noah", atualizadaEm: agora - 30),
            .pasta("sub", [.nota("Outra", atualizadaEm: agora - 7200)]),
        ])]
        let fechada = Fluxo.grafo(itens: [], jobs: [], painel: painel(pastas: pastas))
        XCTAssertFalse(fechada.nos.contains { $0.tipo == .nota })

        let id = Fluxo.pasta("02"), sub = Fluxo.subpasta(id, "sub")
        let aberta = Fluxo.grafo(itens: [], jobs: [], painel: painel(pastas: pastas), abertos: [id])
        let nota = Fluxo.nota(id, "Projeto - Noah")
        XCTAssertEqual(aberta.no(nota)?.detalhe, "nota nova")
        XCTAssertEqual(aberta.ligacao(id, nota)?.estado, .viva)
        XCTAssertEqual(aberta.no(sub)?.detalhe, "1 nota")
        XCTAssertEqual(aberta.no(sub)?.tipo, .pasta)
        XCTAssertNil(aberta.no(Fluxo.nota(sub, "Outra")))

        let funda = Fluxo.grafo(itens: [], jobs: [], painel: painel(pastas: pastas), abertos: [id, sub])
        XCTAssertEqual(funda.no(Fluxo.nota(sub, "Outra"))?.detalhe, "há 2 h")
        XCTAssertEqual(funda.ligacao(sub, Fluxo.nota(sub, "Outra"))?.estado, .parada)
        XCTAssertEqual(Set(funda.nos.map(\.id)).count, funda.nos.count)
    }

    func testPastaComMuitosItensMostraMais() {
        let itens = (1...15).map { ItemCerebro.nota("n\($0)") }
        let pastas = [PastaCerebro(numero: "05", nome: "Estudos", notas: 15, itens: itens)]
        let g = Fluxo.grafo(itens: [], jobs: [], painel: painel(pastas: pastas), abertos: [Fluxo.pasta("05")])
        XCTAssertEqual(g.nos.filter { $0.id.hasPrefix("nota:") }.count, Fluxo.maxFilhos)
        XCTAssertEqual(g.no("mais:\(Fluxo.pasta("05"))")?.nome, "+3")
    }

    func testCerebroSoAcendeComRastro() {
        let semRastro = Fluxo.grafo(itens: [p("a")], jobs: [job("a", "rodando")], painel: painel())
        let doCerebro = semRastro.ligacoes.filter { $0.para == Fluxo.cerebro }
        XCTAssertEqual(doCerebro.count, 3)
        XCTAssertTrue(doCerebro.allSatisfy { $0.estado == .semSinal && $0.rotulo.contains(Fluxo.semSinal) })

        let nota = EventoCentral(quando: agora - 10, tipo: "nota", de: "agente", para: "cerebro",
                                 texto: "02 · Projeto - Noah")
        let comNota = Fluxo.grafo(itens: [], jobs: [], painel: painel(eventos: [nota]))
        XCTAssertEqual(comNota.ligacao(Fluxo.claude, Fluxo.cerebro)?.rotulo, "registrou nota")
        XCTAssertEqual(comNota.ligacao(Fluxo.noah, Fluxo.cerebro)?.estado, .semSinal)
    }

    func testPendenciaAcendeAgenteECentral() {
        let g = Fluxo.grafo(itens: [p("a"), p("b", respondendo: true), p("c", fonte: "codex")], jobs: [])
        XCTAssertEqual(g.ligacao(Fluxo.claude, Fluxo.central)?.quantidade, 1)
        XCTAssertEqual(g.ligacao(Fluxo.claude, Fluxo.central)?.rotulo, "1 pendência")
        XCTAssertEqual(g.ligacao(Fluxo.codex, Fluxo.central)?.estado, .viva)
        XCTAssertEqual(g.ligacao(Fluxo.central, Fluxo.aparelhos)?.rotulo, "2 para fazer")
        XCTAssertEqual(g.ligacao(Fluxo.noah, Fluxo.central)?.estado, .parada)
        XCTAssertTrue(g.aceso(Fluxo.aparelhos))
    }

    func testConversasClaudeMostramSubagentesLigadosAPai() {
        var item = p("sessao123", fonte: "claude")
        item.subagentes = [Subagente(id: "agentabc123"), Subagente(id: "agentdef456")]
        let g = Fluxo.grafo(itens: [item], jobs: [])
        let sessao = Fluxo.conversa("sessao123")
        let primeiro = Fluxo.subagente("sessao123", "agentabc123")
        XCTAssertEqual(g.no(sessao)?.tipo, .conversa)
        XCTAssertEqual(g.ligacao(Fluxo.claude, sessao)?.rotulo, "conversa")
        XCTAssertEqual(g.no(primeiro)?.nome, "Agente agentabc")
        XCTAssertEqual(g.ligacao(sessao, primeiro)?.rotulo, "subagente")
        XCTAssertEqual(Set(g.nos.map(\.id)).count, g.nos.count)
    }

    func testPayloadAntigoEOpcionalDeSubagentesDecodifica() throws {
        let antigo = Data(#"{"fonte":"claude","id":"s1","titulo":"Conversa"}"#.utf8)
        let novo = Data(#"{"fonte":"claude","id":"s2","titulo":"Conversa","subagentes":[{"id":"a1"}]}"#.utf8)
        XCTAssertTrue(try JSONDecoder().decode(Pendencia.self, from: antigo).subagentes.isEmpty)
        XCTAssertEqual(try JSONDecoder().decode(Pendencia.self, from: novo).subagentes, [Subagente(id: "a1")])
    }

    func testConversaAtivaClaudePermaneceNoFluxoEDeduplicaPendencia() throws {
        let raw = Data(#"{"ollama":true,"conversas_claude":[{"id":"ativa","quando":42,"subagentes":[{"id":"side1"}]}]}"#.utf8)
        let painelAtivo = try JSONDecoder().decode(PainelCentral.self, from: raw)
        XCTAssertEqual(painelAtivo.conversasClaude.count, 1)
        XCTAssertTrue(try JSONDecoder().decode(PainelCentral.self, from: Data(#"{"ollama":true}"#.utf8)).conversasClaude.isEmpty)

        var pendente = p("ativa")
        pendente.titulo = "Título preservado"
        pendente.subagentes = [Subagente(id: "side1")]
        let g = Fluxo.grafo(itens: [pendente], jobs: [], painel: painelAtivo)
        XCTAssertEqual(g.nos.filter { $0.id == Fluxo.conversa("ativa") }.count, 1)
        XCTAssertEqual(g.no(Fluxo.conversa("ativa"))?.nome, "Título preservado")
        XCTAssertEqual(g.nos.filter { $0.id == Fluxo.subagente("ativa", "side1") }.count, 1)
    }

    func testGeradaPeloNoahAcendeNoah() {
        let g = Fluxo.grafo(itens: [p("x", fonte: "noah"), p("y", fonte: "noah")], jobs: [])
        XCTAssertEqual(g.ligacao(Fluxo.noah, Fluxo.central)?.rotulo, "2 geradas pelo Noah")
        XCTAssertEqual(g.ligacao(Fluxo.claude, Fluxo.central)?.estado, .parada)
    }

    func testRespostaRodandoVoltaAoAgente() {
        let g = Fluxo.grafo(itens: [], jobs: [job("a", "rodando", fonte: "codex"), job("b", "concluido")])
        XCTAssertEqual(g.ligacao(Fluxo.aparelhos, Fluxo.central)?.rotulo, "1 resposta enviada")
        XCTAssertEqual(g.ligacao(Fluxo.central, Fluxo.codex)?.estado, .viva)
        XCTAssertEqual(g.ligacao(Fluxo.central, Fluxo.claude)?.estado, .parada)
    }

    func sinal(claude: SinalCerebro.Uso = .init(), codex: SinalCerebro.Uso = .init(), noah: SinalCerebro.Uso = .init(),
               falhas: [String] = []) -> SinalCerebro {
        SinalCerebro(janela: 600, cerebro: ["claude": claude, "codex": codex, "noah": noah], falhas: falhas)
    }

    func testPartesDoCerebroPorAgente() {
        let s = sinal(claude: .init(consultas: 2, registros: 1, partes: ["02": 2, "03": 1, "06": 1, "09": 4, "05": 0]),
                      codex: .init(consultas: 1, partes: ["02": 1]),
                      noah: .init(consultas: 1, partes: [:]))
        XCTAssertEqual(Fluxo.partes(.claude, s), [.projetos: 2, .mapas: 1, .logs: 1])
        XCTAssertEqual(Fluxo.partes(.noah, s), [:])
        XCTAssertEqual(Fluxo.visitas(s), [.projetos: [.claude, .codex], .mapas: [.claude], .logs: [.claude]])
        XCTAssertEqual(Fluxo.rotuloDasPartes(Fluxo.partes(.claude, s) ?? [:]), "Projetos, Mapas, Logs")

        let g = Fluxo.grafo(itens: [], jobs: [], cerebro: s)
        XCTAssertEqual(g.ligacao(Fluxo.claude, Fluxo.cerebro)?.estado, .viva)
        XCTAssertEqual(g.ligacao(Fluxo.codex, Fluxo.cerebro)?.rotulo, "1 consulta")
    }

    func testPartesSemSinalNuncaInventam() {
        let antiga = sinal(claude: .init(consultas: 3))
        XCTAssertNil(Fluxo.partes(.claude, antiga))
        XCTAssertNil(Fluxo.partes(.claude, nil))
        let falhou = sinal(codex: .init(consultas: 2, partes: ["02": 2]), falhas: ["Codex"])
        XCTAssertNil(Fluxo.partes(.codex, falhou))
        XCTAssertEqual(Fluxo.visitas(falhou), [:])
        XCTAssertEqual(Fluxo.visitas(nil), [:])
        XCTAssertEqual(Fluxo.Parte.allCases.map(\.rawValue), ["00", "01", "02", "03", "04", "05", "06", "07"])
    }
}
