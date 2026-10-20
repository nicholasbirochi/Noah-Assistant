import XCTest
@testable import NoahCore

final class FluxoTests: XCTestCase {
    func p(_ id: String, fonte: String = "claude", respondendo: Bool = false) -> Pendencia {
        var item = Pendencia(fonte: fonte, ident: id, titulo: id)
        item.respondendo = respondendo
        return item
    }
    func job(_ id: String, _ estado: String, fonte: String = "claude") -> Job {
        Job(id: id, chave: "\(fonte):\(id)", titulo: id, fonte: fonte, estado: estado, inicio: 0)
    }
    func ligacao(_ lista: [Fluxo.Ligacao], _ de: Fluxo.No, _ para: Fluxo.No) -> Fluxo.Ligacao? {
        lista.first { $0.de == de && $0.para == para }
    }

    func testSemDadosNadaFicaVivo() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [])
        XCTAssertEqual(lista.count, 11)
        XCTAssertFalse(lista.contains { $0.estado == .viva })
        XCTAssertEqual(ligacao(lista, .claude, .central)?.rotulo, "nada esperando")
        XCTAssertEqual(Set(lista.map(\.id)).count, lista.count)
    }

    func testPendenciaAcendeAgenteECentral() {
        let lista = Fluxo.ligacoes(itens: [p("a"), p("b", respondendo: true), p("c", fonte: "codex")], jobs: [])
        XCTAssertEqual(ligacao(lista, .claude, .central)?.estado, .viva)
        XCTAssertEqual(ligacao(lista, .claude, .central)?.quantidade, 1)
        XCTAssertEqual(ligacao(lista, .claude, .central)?.rotulo, "1 pendência")
        XCTAssertEqual(ligacao(lista, .codex, .central)?.estado, .viva)
        XCTAssertEqual(ligacao(lista, .central, .aparelhos)?.rotulo, "2 para fazer")
        XCTAssertEqual(ligacao(lista, .noah, .central)?.estado, .parada)
    }

    func testGeradaPeloNoahAcendeNoah() {
        let lista = Fluxo.ligacoes(itens: [p("x", fonte: "noah"), p("y", fonte: "noah")], jobs: [])
        XCTAssertEqual(ligacao(lista, .noah, .central)?.rotulo, "2 geradas pelo Noah")
        XCTAssertEqual(ligacao(lista, .claude, .central)?.estado, .parada)
    }

    func testRespostaRodandoVoltaAoAgente() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [job("a", "rodando", fonte: "codex"), job("b", "concluido")])
        XCTAssertEqual(ligacao(lista, .aparelhos, .central)?.rotulo, "1 resposta enviada")
        XCTAssertEqual(ligacao(lista, .central, .codex)?.estado, .viva)
        XCTAssertEqual(ligacao(lista, .central, .claude)?.estado, .parada)
    }

    func sinal(claude: SinalCerebro.Uso = .init(), codex: SinalCerebro.Uso = .init(), noah: SinalCerebro.Uso = .init(),
               delegClaude: Int = 0, delegCodex: Int = 0, falhas: [String] = []) -> SinalCerebro {
        SinalCerebro(janela: 600, cerebro: ["claude": claude, "codex": codex, "noah": noah],
                     auxiliares: ["claude": .init(delegacoes: delegClaude), "codex": .init(delegacoes: delegCodex)],
                     falhas: falhas)
    }

    func testSinalDoCerebroAcendeQuemConsultou() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [], cerebro: sinal(
            claude: .init(consultas: 2, registros: 1), noah: .init(consultas: 1), delegClaude: 1, delegCodex: 2))
        let claude = ligacao(lista, .claude, .cerebro)
        XCTAssertEqual(claude?.estado, .viva)
        XCTAssertEqual(claude?.quantidade, 3)
        XCTAssertEqual(claude?.rotulo, "2 consultas · 1 registro")
        XCTAssertEqual(ligacao(lista, .noah, .cerebro)?.rotulo, "1 consulta")
        XCTAssertEqual(ligacao(lista, .codex, .cerebro)?.estado, .parada)
        XCTAssertEqual(ligacao(lista, .codex, .cerebro)?.rotulo, "nada nos últimos 10 min")
        XCTAssertEqual(ligacao(lista, .cerebro, .auxiliares)?.rotulo, "3 tarefas delegadas")
        XCTAssertEqual(lista.count, 11)
    }

    func testSinalZeradoDeixaCerebroParado() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [], cerebro: sinal())
        let cerebro = lista.filter { $0.de == .cerebro || $0.para == .cerebro }
        XCTAssertTrue(cerebro.allSatisfy { $0.estado == .parada })
    }

    func testFonteQueFalhouFicaSemSinal() {
        let lista = Fluxo.ligacoes(itens: [], jobs: [], cerebro: sinal(
            codex: .init(consultas: 5), delegClaude: 1, delegCodex: 4, falhas: ["Codex"]))
        XCTAssertEqual(ligacao(lista, .codex, .cerebro)?.estado, .semSinal)
        XCTAssertEqual(ligacao(lista, .claude, .cerebro)?.estado, .parada)
        // Só soma a delegação da fonte que a central leu.
        XCTAssertEqual(ligacao(lista, .cerebro, .auxiliares)?.rotulo, "1 tarefa delegada")
        let semNada = Fluxo.ligacoes(itens: [], jobs: [], cerebro: sinal(falhas: ["Claude Code", "Codex"]))
        XCTAssertEqual(ligacao(semNada, .cerebro, .auxiliares)?.estado, .semSinal)
    }

    func testPartesDoCerebroPorAgente() {
        let s = sinal(claude: .init(consultas: 2, registros: 1, partes: ["02": 2, "03": 1, "06": 1, "09": 4, "05": 0]),
                      codex: .init(consultas: 1, partes: ["02": 1]),
                      noah: .init(consultas: 1, partes: [:]))
        // Código fora de 00–07 e contagem zero não viram parte.
        XCTAssertEqual(Fluxo.partes(.claude, s), [.projetos: 2, .mapas: 1, .logs: 1])
        XCTAssertEqual(Fluxo.partes(.noah, s), [:])
        XCTAssertEqual(Fluxo.visitas(s), [.projetos: [.claude, .codex], .mapas: [.claude], .logs: [.claude]])
        XCTAssertEqual(Fluxo.rotuloDasPartes(Fluxo.partes(.claude, s) ?? [:]), "Projetos, Mapas, Logs")
    }

    func testPartesSemSinalNuncaInventam() {
        // Central antiga (sem "partes"), fonte em falha ou sem sinal: nil, e nenhuma parte acesa.
        let antiga = sinal(claude: .init(consultas: 3))
        XCTAssertNil(Fluxo.partes(.claude, antiga))
        XCTAssertNil(Fluxo.partes(.claude, nil))
        let falhou = sinal(codex: .init(consultas: 2, partes: ["02": 2]), falhas: ["Codex"])
        XCTAssertNil(Fluxo.partes(.codex, falhou))
        XCTAssertEqual(Fluxo.visitas(falhou), [:])
        XCTAssertEqual(Fluxo.visitas(nil), [:])
        XCTAssertEqual(Fluxo.Parte.allCases.map(\.rawValue), ["00", "01", "02", "03", "04", "05", "06", "07"])
    }

    func testCerebroNuncaFingeAtividade() {
        let lista = Fluxo.ligacoes(itens: [p("a"), p("b", fonte: "noah")], jobs: [job("a", "rodando")])
        let cerebro = lista.filter { $0.de == .cerebro || $0.para == .cerebro }
        XCTAssertEqual(cerebro.count, 4)
        XCTAssertTrue(cerebro.allSatisfy { $0.estado == .semSinal && $0.rotulo.contains(Fluxo.semSinal) })
    }
}
