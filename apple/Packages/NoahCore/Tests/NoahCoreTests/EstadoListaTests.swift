import Foundation
import XCTest
@testable import NoahCore

final class EstadoListaTests: XCTestCase {
    func testAntesDaPrimeiraRespostaMostraConectando() {
        XCTAssertEqual(EstadoLista.de(atualizadoEm: nil, erro: nil, temItens: false), .conectando)
    }

    func testNadaEsperandoSoDepoisDeLeituraVazia() {
        XCTAssertEqual(EstadoLista.de(atualizadoEm: Date(), erro: nil, temItens: false), .vazio)
    }

    func testErroNaoViraNadaEsperando() {
        // Sem nenhuma leitura ou depois de uma: a lista mostra o aviso vermelho.
        XCTAssertEqual(EstadoLista.de(atualizadoEm: nil, erro: "sem rede", temItens: false), .erro)
        XCTAssertEqual(EstadoLista.de(atualizadoEm: Date(), erro: "sem rede", temItens: false), .erro)
    }

    func testComItensOuRespostasNaoHaEstadoVazio() {
        XCTAssertEqual(EstadoLista.de(atualizadoEm: Date(), erro: nil, temItens: true), .itens)
        // Itens antigos seguem na tela quando uma leitura posterior falha.
        XCTAssertEqual(EstadoLista.de(atualizadoEm: Date(), erro: "sem rede", temItens: true), .itens)
    }
}
