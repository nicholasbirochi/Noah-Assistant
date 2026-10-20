#if os(iOS)
import ActivityKit
import NoahCore

/// A Live Activity do Noah (ilha dinâmica e tela bloqueada). Só tem uma por vez;
/// o estado é o mesmo resumo que os widgets leem do App Group.
struct NoahAtributos: ActivityAttributes {
    typealias ContentState = ResumoIlha
}
#endif
