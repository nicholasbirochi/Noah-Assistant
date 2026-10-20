import Foundation
import NoahCore

/// Endereço da central e resposta do "Aceitar" ficam em UserDefaults; o token,
/// no Keychain. Leitura estática porque os avisos agem até com o app fechado.
/// Para testar, `-endereco http://127.0.0.1:8779` na linha de comando também vale
/// (domínio de argumentos do UserDefaults).
enum Ajustes {
    static let enderecoPadrao = "http://127.0.0.1:8769"
    private static let chaveEndereco = "endereco"
    private static let chaveAceitar = "respostaAceitar"

    static var endereco: String {
        get { UserDefaults.standard.string(forKey: chaveEndereco) ?? enderecoPadrao }
        set { UserDefaults.standard.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: chaveEndereco) }
    }

    static var respostaAceitar: String {
        get {
            let salvo = UserDefaults.standard.string(forKey: chaveAceitar)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return salvo.isEmpty ? RespostaRapida.aceitar : salvo
        }
        set { UserDefaults.standard.set(newValue, forKey: chaveAceitar) }
    }

    static func cliente() throws -> ClienteCentral {
        guard let base = ClienteCentral.endereco(endereco) else { throw ErroCentral.enderecoInvalido }
        return ClienteCentral(base: base, token: Cofre.ler())
    }
}
