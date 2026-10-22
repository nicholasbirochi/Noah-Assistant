import Foundation

/// Valida a transmissão PCM antes de entregá-la ao reprodutor.
public enum AudioDaCentral {
    public static func pcm(_ dados: Data) throws -> Data {
        var posicao = 0
        var audio = Data()
        while dados.count - posicao >= 4 {
            let tamanho = dados[posicao..<(posicao + 4)].reduce(0) { ($0 << 8) | Int($1) }
            posicao += 4
            if tamanho == 0 {
                guard posicao == dados.count, !audio.isEmpty else {
                    throw ErroCentral.rede("Áudio da voz inválido")
                }
                return audio
            }
            guard tamanho <= 4_000_000, tamanho.isMultiple(of: 2),
                  audio.count + tamanho <= 40_000_000,
                  tamanho <= dados.count - posicao else {
                throw ErroCentral.rede("Formato da voz inválido")
            }
            audio.append(dados[posicao..<(posicao + tamanho)])
            posicao += tamanho
        }
        throw ErroCentral.rede("A transmissão da voz foi interrompida")
    }
}
