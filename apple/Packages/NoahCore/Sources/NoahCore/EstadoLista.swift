import Foundation

/// O que a lista de Pendências mostra no lugar dos itens. "Nada esperando você"
/// só depois de uma leitura bem-sucedida e vazia; antes da primeira resposta da
/// central, "Conectando…". Com erro, a própria lista já traz o aviso em vermelho.
public enum EstadoLista: Equatable, Sendable {
    case conectando, vazio, erro, itens

    public static func de(atualizadoEm: Date?, erro: String?, temItens: Bool) -> EstadoLista {
        if temItens { return .itens }
        if erro != nil { return .erro }
        return atualizadoEm == nil ? .conectando : .vazio
    }
}
