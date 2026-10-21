import Foundation
import XCTest
@testable import NoahCore

final class VozTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_000)

    func testFechaAFraseSoDepoisDaPausa() {
        var turno = TurnoDeVoz(silencio: 1.4)
        turno.ouviu("como está", em: t0)
        turno.ouviu("como está o build", em: t0.addingTimeInterval(0.8))
        XCTAssertNil(turno.fechar(em: t0.addingTimeInterval(1.5)))
        XCTAssertEqual(turno.fechar(em: t0.addingTimeInterval(2.3)), "como está o build")
        XCTAssertTrue(turno.parcial.isEmpty)
        XCTAssertNil(turno.fechar(em: t0.addingTimeInterval(9)))
    }

    func testTrechoRepetidoNaoAdiaAPausa() {
        var turno = TurnoDeVoz(silencio: 1)
        turno.ouviu("oi Noah", em: t0)
        turno.ouviu(" oi Noah ", em: t0.addingTimeInterval(0.9))
        XCTAssertEqual(turno.fechar(em: t0.addingTimeInterval(1.1)), "oi Noah")
    }

    func testRuidoNaoViraMensagem() {
        var turno = TurnoDeVoz(silencio: 1)
        turno.ouviu("é", em: t0)
        XCTAssertNil(turno.fechar(em: t0.addingTimeInterval(2)))
        XCTAssertTrue(turno.parcial.isEmpty)
    }

    func testDescartarEsqueceAFrase() {
        var turno = TurnoDeVoz(silencio: 1)
        turno.ouviu("isso não era para você", em: t0)
        turno.descartar()
        XCTAssertNil(turno.fechar(em: t0.addingTimeInterval(5)))
    }

    func testLimpaMarkdownAntesDeFalar() {
        let r = """
        ## Pronto
        - **Testes** passaram, veja [o relatório](https://exemplo.test/r).
        ```swift
        print("oi")
        ```
        Use `swift test`.
        """
        XCTAssertEqual(FalaDoNoah.paraFalar(r),
                       "Pronto Testes passaram, veja o relatório. (código no chat) Use swift test.")
    }

    func testRespostaLongaCortaNaUltimaFrase() {
        let r = String(repeating: "Uma frase curta aqui. ", count: 60)
        let falado = FalaDoNoah.paraFalar(r, limite: 100)
        XCTAssertTrue(falado.hasSuffix("aqui. O resto está no chat."), falado)
        XCTAssertLessThan(falado.count, 140)
    }
}
