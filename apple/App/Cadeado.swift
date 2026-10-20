import Foundation
import LocalAuthentication

/// Aprovação com Face ID no iPhone (Touch ID ou senha no Mac) antes de mandar
/// algo para um agente. Fica no `Modelo`, então vale para todo botão do app,
/// e os links da ilha e dos widgets só abrem o app: nada aprova sem passar aqui.
enum Cadeado {
    /// `true` se pode seguir. Sem senha configurada no aparelho não há o que
    /// pedir, e segue, como faz o iOS nas ações de aviso com `.authenticationRequired`.
    @MainActor
    static func confirmar(_ motivo: String) async -> Bool {
        guard Ajustes.pedirBiometria else { return true }
        let ctx = LAContext()
        ctx.localizedCancelTitle = "Cancelar"
        var erro: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &erro) else {
            return (erro as? LAError)?.code == .passcodeNotSet
        }
        return (try? await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: motivo)) ?? false
    }

    /// Nome do que o aparelho usa, para os textos ("Face ID", "Touch ID"…).
    static var nome: String {
        let ctx = LAContext()
        _ = ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        switch ctx.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .opticID: return "Optic ID"
        default: return "senha do aparelho"
        }
    }
}
