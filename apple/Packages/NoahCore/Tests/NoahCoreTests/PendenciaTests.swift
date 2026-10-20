import XCTest
@testable import NoahCore

final class PendenciaTests: XCTestCase {
    let doNoah = Pendencia(fonte: "noah", ident: "p-1", titulo: "propostas", projeto: "Noah",
                           mensagem: "Há 2 propostas paradas há 3 dias.\n\n→ Revise as propostas no Cérebro.",
                           podeResponder: false)
    let conversa = Pendencia(fonte: "claude", ident: "c-1", titulo: "Ajustar o login", projeto: "Site",
                             mensagem: "Terminei. Posso commitar?")

    func testItemDoNoahViraTarefaComAAcao() {
        XCTAssertTrue(doNoah.automatica)
        XCTAssertEqual(doNoah.tarefa, "Revise as propostas no Cérebro.")
        XCTAssertEqual(doNoah.acao, "Revise as propostas no Cérebro.")
        XCTAssertEqual(doNoah.motivo, "Há 2 propostas paradas há 3 dias.")
        XCTAssertEqual(doNoah.origem, "Gerada automaticamente pelo Noah a partir de propostas.")
    }

    func testConversaUsaOTituloEAMensagemInteira() {
        XCTAssertFalse(conversa.automatica)
        XCTAssertEqual(conversa.tarefa, "Ajustar o login")
        XCTAssertNil(conversa.acao)
        XCTAssertEqual(conversa.motivo, "Terminei. Posso commitar?")
        XCTAssertEqual(conversa.origem, "Claude terminou e está esperando sua resposta.")
    }

    func testItemDoNoahSemAcaoCaiNoTitulo() {
        let semAcao = Pendencia(fonte: "noah", ident: "p-2", titulo: "lembrete", mensagem: "Só o porquê.")
        XCTAssertEqual(semAcao.tarefa, "lembrete")
        XCTAssertEqual(semAcao.motivo, "Só o porquê.")
    }

    func testSepararMantemAOrdemDaCentral() {
        let codex = Pendencia(fonte: "codex", ident: "x", titulo: "x")
        let (conversas, automaticas) = Pendencia.separar([conversa, doNoah, codex])
        XCTAssertEqual(conversas.map(\.chave), ["claude:c-1", "codex:x"])
        XCTAssertEqual(automaticas.map(\.chave), ["noah:p-1"])
    }
}
