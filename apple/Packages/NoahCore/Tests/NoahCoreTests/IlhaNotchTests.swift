import CoreGraphics
import Foundation
import XCTest
@testable import NoahCore

final class IlhaNotchTests: XCTestCase {
    let t0 = Date(timeIntervalSince1970: 1_000_000)

    func testPilulaComNotchAbreAsasDosLados() {
        let notch = CGSize(width: 200, height: 32)
        XCTAssertEqual(IlhaNotch.tamanhoFechado(.esperando, notch: notch, barra: 24), CGSize(width: 368, height: 32))
        XCTAssertEqual(IlhaNotch.tamanhoFechado(.quieto, notch: notch, barra: 24), CGSize(width: 268, height: 32))
    }

    func testPilulaSemNotchFicaNaAlturaDaBarra() {
        XCTAssertEqual(IlhaNotch.tamanhoFechado(.trabalhando, notch: .zero, barra: 24), CGSize(width: 190, height: 24))
        XCTAssertEqual(IlhaNotch.tamanhoFechado(.quieto, notch: .zero, barra: 24), CGSize(width: 120, height: 24))
    }

    func testEspiaSoQuandoAumenta() {
        XCTAssertTrue(IlhaNotch.deveEspiar(antes: 0, depois: 1))
        XCTAssertFalse(IlhaNotch.deveEspiar(antes: 2, depois: 1))
        XCTAssertFalse(IlhaNotch.deveEspiar(antes: 1, depois: 1))
    }

    func testAbreNoHoverEFechaDepoisDaFolga() {
        var s = IlhaNotch.Seguidor()
        XCTAssertEqual(s.passo(dentro: true, agora: t0), .abrir)
        XCTAssertEqual(s.passo(dentro: true, agora: t0 + 0.1), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 0.2), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 0.7), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 0.9), .fechar)
        XCTAssertFalse(s.aberta)
    }

    func testVoltarAntesDaFolgaMantemAberta() {
        var s = IlhaNotch.Seguidor()
        _ = s.passo(dentro: true, agora: t0)
        _ = s.passo(dentro: false, agora: t0 + 0.1)
        _ = s.passo(dentro: true, agora: t0 + 0.3)
        // A contagem recomeça: sair de novo ainda dá a folga inteira.
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 0.5), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 0.7), .nada)
        XCTAssertTrue(s.aberta)
    }

    func testEspiarFicaAbertaComMouseLonge() {
        var s = IlhaNotch.Seguidor()
        XCTAssertEqual(s.espiar(agora: t0), .abrir)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 1), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 3.9), .nada)
        XCTAssertTrue(s.aberta)
        // Passado o tempo de espiar, a folga normal começa a contar.
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 4.1), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 4.5), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 4.8), .fechar)
    }

    func testFecharZeraOEspiar() {
        var s = IlhaNotch.Seguidor()
        _ = s.espiar(agora: t0)
        XCTAssertEqual(s.fechar(), .fechar)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 1), .nada)
        XCTAssertFalse(s.aberta)
    }

    func testEscrevendoSeguraAbertaComMouseLonge() {
        var s = IlhaNotch.Seguidor()
        _ = s.passo(dentro: true, agora: t0)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 0.2, segurar: true), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 5, segurar: true), .nada)
        XCTAssertTrue(s.aberta)
        // Largou o campo: a folga normal volta a contar a partir daí.
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 5.1), .nada)
        XCTAssertEqual(s.passo(dentro: false, agora: t0 + 5.8), .fechar)
    }

    func testSegurarComAIlhaFechadaNaoAbre() {
        var s = IlhaNotch.Seguidor()
        XCTAssertEqual(s.passo(dentro: false, agora: t0, segurar: true), .nada)
        XCTAssertFalse(s.aberta)
    }

    func testZonaAbertaCobreBordaESombra() {
        // Cartão de 440×244 colado no topo de uma tela de 1440 de altura.
        let cartao = CGRect(x: 1060, y: 1440 - 244, width: 440, height: 244)
        let z = IlhaNotch.zonaDeHover(cartao, aberta: true)
        XCTAssertTrue(z.contains(CGPoint(x: 1280, y: 1440 - 252)), "logo abaixo da borda de baixo")
        XCTAssertTrue(z.contains(CGPoint(x: 1045, y: 1300)), "na sombra à esquerda")
        XCTAssertTrue(z.contains(CGPoint(x: 1280, y: 1440)), "no topo da tela")
        XCTAssertFalse(z.contains(CGPoint(x: 1280, y: 1440 - 280)), "longe embaixo")
        XCTAssertFalse(z.contains(CGPoint(x: 1530, y: 1300)), "longe à direita")
    }

    func testZonaFechadaTemPoucaFolga() {
        let pilula = CGRect(x: 1185, y: 1416, width: 190, height: 24)
        let z = IlhaNotch.zonaDeHover(pilula, aberta: false)
        XCTAssertTrue(z.contains(CGPoint(x: 1180, y: 1430)))
        XCTAssertFalse(z.contains(CGPoint(x: 1280, y: 1400)), "não abre do meio da tela")
    }

    func testSemAlcoveFicaNoMeio() {
        let p = IlhaNotch.posicao(tela: 0...2560, largura: 480, alcove: nil)
        XCTAssertEqual(p, IlhaNotch.Posicao(x: 1040, alinhamento: .centro))
    }

    func testComAlcoveEncostaADireita() {
        let p = IlhaNotch.posicao(tela: 0...2560, largura: 480, alcove: 968...1592)
        XCTAssertEqual(p, IlhaNotch.Posicao(x: 1600, alinhamento: .esquerda))
    }

    func testSemNotchFicaADireitaSemChegarNosIcones() {
        let limite = 2560 - IlhaNotch.reservaIcones
        let p = IlhaNotch.posicao(tela: 0...2560, largura: 480, alcove: 968...1592, limiteDireita: limite)
        XCTAssertEqual(p, IlhaNotch.Posicao(x: 1600, alinhamento: .esquerda))
        XCTAssertLessThanOrEqual(p.x + 480, limite)
        // Com os ícones mais perto do meio, a direita não cabe: vai para a esquerda.
        let q = IlhaNotch.posicao(tela: 0...2560, largura: 480, alcove: 968...1592, limiteDireita: 1900)
        XCTAssertEqual(q, IlhaNotch.Posicao(x: 480, alinhamento: .direita))
    }

    func testAlcoveSemEspacoADireitaVaiParaAEsquerda() {
        let p = IlhaNotch.posicao(tela: 0...1512, largura: 480, alcove: 900...1300)
        XCTAssertEqual(p, IlhaNotch.Posicao(x: 412, alinhamento: .direita))
    }

    func testTelaPequenaDemaisVoltaParaOMeio() {
        let p = IlhaNotch.posicao(tela: 0...800, largura: 480, alcove: 100...700)
        XCTAssertEqual(p.alinhamento, .centro)
    }
}
