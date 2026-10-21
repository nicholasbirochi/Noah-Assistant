import Foundation
import Security

/// Token da central no Keychain (nunca em UserDefaults).
enum Cofre {
    private static let servico = "com.nicholasbirochi.noah.central"
    private static let conta = "token"

    private static var consulta: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: servico,
         kSecAttrAccount as String: conta]
    }

    enum Erro: LocalizedError {
        case keychain(OSStatus)
        case confirmacao
        case dadoInvalido

        var errorDescription: String? {
            switch self {
            case .keychain(let status): "O Keychain recusou a operação (código \(status))."
            case .confirmacao: "O Keychain não confirmou o token salvo."
            case .dadoInvalido: "O Keychain retornou um dado que não é texto válido."
            }
        }
    }

    static func ler() -> String? {
        try? lerConfirmado()
    }

    /// Texto vazio apaga o token. Uma falha nunca apaga o valor anterior.
    static func gravar(_ token: String) throws {
        let limpo = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if limpo.isEmpty {
            let status = SecItemDelete(consulta as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else {
                throw Erro.keychain(status)
            }
            guard try lerConfirmado() == nil else { throw Erro.confirmacao }
            return
        }

        var atributos: [String: Any] = [kSecValueData as String: Data(limpo.utf8)]
        #if os(iOS)
        // Depois do primeiro desbloqueio: a atualização em segundo plano precisa ler.
        atributos[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        #endif

        let atualizado = SecItemUpdate(consulta as CFDictionary, atributos as CFDictionary)
        if atualizado == errSecItemNotFound {
            var novoItem = consulta
            novoItem.merge(atributos) { _, valor in valor }
            let adicionado = SecItemAdd(novoItem as CFDictionary, nil)
            if adicionado == errSecDuplicateItem {
                // Outro salvamento pode ter criado o item entre update e add.
                let corrida = SecItemUpdate(consulta as CFDictionary, atributos as CFDictionary)
                guard corrida == errSecSuccess else { throw Erro.keychain(corrida) }
            } else if adicionado != errSecSuccess {
                throw Erro.keychain(adicionado)
            }
        } else if atualizado != errSecSuccess {
            throw Erro.keychain(atualizado)
        }

        guard try lerConfirmado() == limpo else { throw Erro.confirmacao }
    }

    private static func lerConfirmado() throws -> String? {
        var q = consulta
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var dado: AnyObject?
        let status = SecItemCopyMatching(q as CFDictionary, &dado)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw Erro.keychain(status) }
        guard let bytes = dado as? Data,
              let texto = String(data: bytes, encoding: .utf8) else {
            throw Erro.dadoInvalido
        }
        return texto.isEmpty ? nil : texto
    }
}
