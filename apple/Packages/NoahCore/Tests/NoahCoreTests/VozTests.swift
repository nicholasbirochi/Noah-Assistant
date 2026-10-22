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

    func testDetectorDeVozToleraPisoBaixoMasRejeitaRuido() {
        var detector = DetectorDeVoz()
        for _ in 0..<40 { XCTAssertFalse(detector.atualizar(rms: 0.004)) }
        XCTAssertFalse(detector.atualizar(rms: 0.03))
        XCTAssertFalse(detector.atualizar(rms: 0.03))
        XCTAssertTrue(detector.atualizar(rms: 0.03))
        for _ in 0..<11 { XCTAssertTrue(detector.atualizar(rms: 0.004)) }
        XCTAssertFalse(detector.atualizar(rms: 0.004))
    }

    func testVozContinuaValidaSeATranscricaoChegarDepoisDoSilencio() {
        var detector = DetectorDeVoz()
        for _ in 0..<3 { detector.atualizar(rms: 0.03) }
        for _ in 0..<100 { detector.atualizar(rms: 0.004) }
        XCTAssertFalse(detector.vozAtiva)
        XCTAssertTrue(detector.teveVozNoPedido)
        detector.novoPedido()
        XCTAssertFalse(detector.teveVozNoPedido)
        for _ in 0..<100 { detector.atualizar(rms: 0.004) }
        XCTAssertFalse(detector.teveVozNoPedido)
    }

    func testReconhecimentoDescartaFragmentosDeRuidoMasMantemOi() {
        XCTAssertFalse(TurnoDeVoz.pareceFala("é"))
        XCTAssertFalse(TurnoDeVoz.pareceFala("x!"))
        XCTAssertTrue(TurnoDeVoz.pareceFala(" oi "))
        XCTAssertTrue(TurnoDeVoz.pareceFala("não"))
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

final class AudioDaCentralTests: XCTestCase {
    func testReuneOsBlocosAntesDeReproduzirSemPausasDaRede() throws {
        let dados = Data([0, 0, 0, 2, 1, 2, 0, 0, 0, 4, 3, 4, 5, 6, 0, 0, 0, 0])
        XCTAssertEqual(try AudioDaCentral.pcm(dados), Data([1, 2, 3, 4, 5, 6]))
    }

    func testRejeitaTransmissaoTruncadaVaziaOuComLixoAposOFim() {
        for bytes: [UInt8] in [[], [0], [0, 0, 0, 0], [0, 0, 0, 4, 1, 2],
                               [0, 0, 0, 2, 1, 2], [0, 0, 0, 2, 1, 2, 0, 0, 0, 0, 7]] {
            XCTAssertThrowsError(try AudioDaCentral.pcm(Data(bytes)))
        }
    }

    func testRejeitaAmostraIncompletaEBlocoGigante() {
        XCTAssertThrowsError(try AudioDaCentral.pcm(Data([0, 0, 0, 1, 1, 0, 0, 0, 0])))
        XCTAssertThrowsError(try AudioDaCentral.pcm(Data([255, 255, 255, 255])))
    }
}
