// swift-tools-version: 5.9
import PackageDescription

// Núcleo do app Noah (iPhone e Mac): modelos da API da central, cliente HTTP e a
// regra de sincronização dos avisos. Sem UI, para rodar em `swift test`.
let package = Package(
    name: "NoahCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "NoahCore", targets: ["NoahCore"])],
    targets: [
        .target(name: "NoahCore"),
        .testTarget(name: "NoahCoreTests", dependencies: ["NoahCore"]),
    ]
)
