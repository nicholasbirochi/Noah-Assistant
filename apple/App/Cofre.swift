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

    static func ler() -> String? {
        var q = consulta
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var dado: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &dado) == errSecSuccess,
              let bytes = dado as? Data, let texto = String(data: bytes, encoding: .utf8),
              !texto.isEmpty else { return nil }
        return texto
    }

    /// Texto vazio apaga o token.
    @discardableResult
    static func gravar(_ token: String) -> Bool {
        SecItemDelete(consulta as CFDictionary)
        let limpo = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !limpo.isEmpty else { return true }
        var q = consulta
        q[kSecValueData as String] = Data(limpo.utf8)
        #if os(iOS)
        // Depois do primeiro desbloqueio: a atualização em segundo plano precisa ler.
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        #endif
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }
}
