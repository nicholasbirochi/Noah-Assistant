import Foundation
import XCTest
@testable import NoahCore

final class IlhaTests: XCTestCase {
    let agora: Double = 1_000_000

    func p(_ id: String, fonte: String = "claude", respondendo: Bool = false) -> Pendencia {
        Pendencia(fonte: fonte, ident: id, titulo: "tarefa \(id)", versao: "1", respondendo: respondendo)
    }

    func job(_ id: String, _ estado: String, fim: Double? = nil) -> Job {
        Job(id: id, chave: "codex:\(id)", titulo: "job \(id)", fonte: "codex", estado: estado,
            inicio: agora - 60, fim: fim)
    }

    func testSemNadaFicaQuieto() {
        let r = Ilha.resumo(itens: [], jobs: [], agora: agora)
        XCTAssertEqual(r.estado, .quieto)
        XCTAssertEqual(r.curto, "Tudo calmo")
    }

    func testPendenciaAbertaVenceTrabalho() {
        let r = Ilha.resumo(itens: [p("a"), p("b")], jobs: [job("x", "rodando")], agora: agora)
        XCTAssertEqual(r.estado, .esperando)
        XCTAssertEqual(r.esperando, 2)
        XCTAssertEqual(r.rodando, 1)
        XCTAssertEqual(r.linha, "tarefa a")
        XCTAssertEqual(r.chave, "claude:a")
        XCTAssertEqual(r.curto, "2 esperando")
    }

    func testQuemEstaRespondendoContaComoTrabalho() {
        let r = Ilha.resumo(itens: [p("a", respondendo: true)], jobs: [], agora: agora)
        XCTAssertEqual(r.estado, .trabalhando)
        XCTAssertEqual(r.rodando, 1)
        XCTAssertEqual(r.esperando, 0)
        XCTAssertEqual(r.agente, Fonte.nome("claude"))
    }

    func testJobConcluidoHaPoucoFicaPronto() {
        let r = Ilha.resumo(itens: [], jobs: [job("x", "concluido", fim: agora - 30)], agora: agora)
        XCTAssertEqual(r.estado, .pronto)
        XCTAssertEqual(r.prontas, 1)
        XCTAssertEqual(r.linha, "job x")
        XCTAssertEqual(r.curto, "Tudo pronto")
    }

    func testJobAntigoOuComErroNaoViraPronto() {
        let jobs = [job("x", "concluido", fim: agora - Sincronia.jobVisivel - 1),
                    job("y", "erro", fim: agora - 10)]
        XCTAssertEqual(Ilha.resumo(itens: [], jobs: jobs, agora: agora).estado, .quieto)
    }

    func testMesmoConteudoIgnoraHora() {
        let a = Ilha.resumo(itens: [p("a")], jobs: [], agora: agora)
        let b = Ilha.resumo(itens: [p("a")], jobs: [], agora: agora + 20)
        XCTAssertNotEqual(a, b)
        XCTAssertTrue(a.mesmoConteudo(b))
        XCTAssertFalse(a.mesmoConteudo(Ilha.resumo(itens: [p("b")], jobs: [], agora: agora)))
    }

    func testGravaELeNoUserDefaults() throws {
        let suite = "IlhaTests-\(UUID().uuidString)"
        let d = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { d.removePersistentDomain(forName: suite) }
        XCTAssertNil(Ilha.ler(de: d))
        let r = Ilha.resumo(itens: [p("a")], jobs: [], agora: agora)
        Ilha.gravar(r, em: d)
        XCTAssertEqual(Ilha.ler(de: d), r)
    }

    func testAtalhosIdaEVolta() {
        let url = Atalho.pendencia("claude:abc 1")
        XCTAssertEqual(url.scheme, "noah")
        XCTAssertEqual(Atalho.destino(url), .pendencia("claude:abc 1"))
        XCTAssertEqual(Atalho.destino(Atalho.lista), .lista)
        XCTAssertEqual(Atalho.destino(Atalho.fluxo), .fluxo)
        XCTAssertEqual(Atalho.destino(URL(string: "noah://pendencia")!), .lista)
        XCTAssertNil(Atalho.destino(URL(string: "https://exemplo.com")!))
        XCTAssertNil(Atalho.destino(URL(string: "noah://outra")!))
    }

    func testAtalhoDoResumo() {
        let esperando = Ilha.resumo(itens: [p("a")], jobs: [], agora: agora)
        XCTAssertEqual(Atalho.destino(Atalho.para(esperando)), .pendencia("claude:a"))
        let pronto = Ilha.resumo(itens: [], jobs: [job("x", "concluido", fim: agora)], agora: agora)
        XCTAssertEqual(Atalho.destino(Atalho.para(pronto)), .fluxo)
        XCTAssertEqual(Atalho.destino(Atalho.para(.vazio)), .lista)
    }
}

final class FonteAppTests: XCTestCase {
    func testAppDeCadaAgente() {
        XCTAssertEqual(Fonte.app("claude"), "com.anthropic.claudefordesktop")
        XCTAssertEqual(Fonte.app("codex"), "com.openai.codex")
        XCTAssertNil(Fonte.app("noah"))
    }
}
