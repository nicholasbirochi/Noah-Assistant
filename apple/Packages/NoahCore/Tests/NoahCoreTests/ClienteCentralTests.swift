import Foundation
import XCTest
@testable import NoahCore

/// Responde no lugar da rede: guarda o pedido e devolve o que o teste mandar.
final class Stub: URLProtocol {
    nonisolated(unsafe) static var resposta: (Int, String) = (200, "{}")
    nonisolated(unsafe) static var pedidos: [URLRequest] = []
    nonisolated(unsafe) static var corpos: [Data] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Stub.pedidos.append(request)
        if let stream = request.httpBodyStream {
            stream.open()
            var dados = Data(), buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }
                dados.append(buffer, count: n)
            }
            stream.close()
            Stub.corpos.append(dados)
        } else {
            Stub.corpos.append(request.httpBody ?? Data())
        }
        let (status, corpo) = Stub.resposta
        let r = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
                                headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: r, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(corpo.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class ClienteCentralTests: XCTestCase {
    var cliente: ClienteCentral!

    override func setUp() {
        Stub.pedidos = []
        Stub.corpos = []
        Stub.resposta = (200, "{}")
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [Stub.self]
        cliente = ClienteCentral(base: URL(string: "http://192.168.0.10:8769")!, token: "segredo",
                                 sessao: URLSession(configuration: config))
    }

    let item = Pendencia(fonte: "claude", ident: "s1", titulo: "Conversa", versao: "v1")

    func testEnderecoAceitaFormasComunsERecusaLixo() {
        XCTAssertEqual(ClienteCentral.endereco("192.168.0.10:8769")?.absoluteString, "http://192.168.0.10:8769")
        XCTAssertEqual(ClienteCentral.endereco(" http://mac.local:8769/ ")?.absoluteString, "http://mac.local:8769")
        XCTAssertNil(ClienteCentral.endereco(""))
        XCTAssertNil(ClienteCentral.endereco("ftp://x:1"))
        XCTAssertNil(ClienteCentral.endereco("http://x:8769/central/api"))
    }

    func testLePendenciasDoJsonDaCentral() async throws {
        Stub.resposta = (200, """
        {"itens":[{"fonte":"claude","id":"s1","titulo":"Conversa","projeto":"proj","quando":"2026-10-19T10:00",
          "mensagem":"Posso seguir?","versao":"v1","pode_responder":true,"chave":"claude:s1","respondendo":false},
          {"fonte":"noah","id":"p-1","titulo":"Lembretes","projeto":"Noah","quando":"","mensagem":"2 vencidos",
          "versao":"p-1","pode_responder":false,"chave":"noah:p-1","respondendo":false}],
         "respondendo":[{"id":"j1","chave":"claude:s1","titulo":"Conversa","fonte":"claude","estado":"rodando",
          "detalhe":"","inicio":1760000000.5,"fim":null}],
         "falhas":["Codex"],"gerado_em":1760000001.0}
        """)
        let r = try await cliente.pendencias()
        XCTAssertEqual(r.itens.map(\.chave), ["claude:s1", "noah:p-1"])
        XCTAssertEqual(r.itens[1].podeResponder, false)
        XCTAssertEqual(r.falhas, ["Codex"])
        XCTAssertEqual(r.respondendo.first?.rodando, true)
        XCTAssertNil(r.respondendo.first?.fim)
        let pedido = try XCTUnwrap(Stub.pedidos.first)
        XCTAssertEqual(pedido.url?.absoluteString, "http://192.168.0.10:8769/central/api/pendencias")
        XCTAssertEqual(pedido.value(forHTTPHeaderField: "Authorization"), "Bearer segredo")
        XCTAssertNil(pedido.value(forHTTPHeaderField: "Origin"))
    }

    func testLePresenca() async throws {
        Stub.resposta = (200, """
        {"ligada":true,"variavel":"NOAH_PRESENCE_ENABLED","itens":[{"source":"Agenda","why":"reunião às 15h",
         "action":"Revise a pauta"}],"falhas":[],"gerado_em":1}
        """)
        let p = try await cliente.presenca()
        XCTAssertTrue(p.ligada)
        XCTAssertEqual(p.itens, [ItemPresenca(source: "Agenda", why: "reunião às 15h", action: "Revise a pauta")])
    }

    func testResponderMandaJsonComTextoLimpo() async throws {
        Stub.resposta = (202, """
        {"job":{"id":"j1","chave":"claude:s1","titulo":"Conversa","fonte":"claude","estado":"rodando",
         "detalhe":"","inicio":1.0,"fim":null}}
        """)
        let job = try await cliente.responder(item, texto: "  Pode seguir.  ")
        XCTAssertEqual(job.chave, "claude:s1")
        let pedido = try XCTUnwrap(Stub.pedidos.first)
        XCTAssertEqual(pedido.httpMethod, "POST")
        XCTAssertEqual(pedido.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let corpo = try JSONDecoder().decode([String: String].self, from: Stub.corpos[0])
        XCTAssertEqual(corpo, ["fonte": "claude", "id": "s1", "texto": "Pode seguir."])
    }

    func testResponderRecusaVazioELongoSemIrARede() async {
        for (texto, esperado) in [("   ", ErroCentral.textoVazio),
                                  (String(repeating: "x", count: 4001), ErroCentral.textoLongo)] {
            do {
                try await cliente.responder(item, texto: texto)
                XCTFail("deveria recusar")
            } catch {
                XCTAssertEqual(error as? ErroCentral, esperado)
            }
        }
        XCTAssertTrue(Stub.pedidos.isEmpty)
    }

    func testErrosDaCentralViramMensagem() async {
        Stub.resposta = (404, #"{"erro":"pendência não encontrada (já respondida ou fora da lista)"}"#)
        do {
            try await cliente.dispensar(item)
            XCTFail("deveria falhar")
        } catch {
            XCTAssertEqual(error as? ErroCentral,
                           .servidor(status: 404, mensagem: "pendência não encontrada (já respondida ou fora da lista)"))
        }
        Stub.resposta = (401, #"{"erro":"token ausente ou inválido"}"#)
        do {
            _ = try await cliente.pendencias()
            XCTFail("deveria falhar")
        } catch {
            XCTAssertEqual(error as? ErroCentral, .naoAutorizado)
        }
    }

    func testDispensar() async throws {
        Stub.resposta = (200, #"{"dispensada":"claude:s1"}"#)
        try await cliente.dispensar(item)
        let corpo = try JSONDecoder().decode([String: String].self, from: Stub.corpos[0])
        XCTAssertEqual(corpo, ["fonte": "claude", "id": "s1"])
        XCTAssertEqual(Stub.pedidos[0].url?.path, "/central/api/dispensar")
    }

    func testPartesDaChave() {
        XCTAssertEqual(ClienteCentral.partes(daChave: "codex:abc:1")?.fonte, "codex")
        XCTAssertEqual(ClienteCentral.partes(daChave: "codex:abc:1")?.ident, "abc:1")
        XCTAssertNil(ClienteCentral.partes(daChave: "semdois"))
        XCTAssertNil(ClienteCentral.partes(daChave: ":x"))
    }
}
