import ActivityKit
import NoahCore
import SwiftUI
import WidgetKit

@main
struct NoahWidgets: WidgetBundle {
    var body: some Widget {
        PainelWidget()
        IlhaAoVivo()
    }
}

// MARK: - Widgets (tela inicial e tela bloqueada)

struct Entrada: TimelineEntry {
    var date: Date
    var resumo: ResumoIlha
}

/// Lê o resumo que o app grava no App Group. O app recarrega os widgets quando
/// o conteúdo muda; a cada 15 min o próprio widget relê, por garantia.
struct Provedor: TimelineProvider {
    func placeholder(in context: Context) -> Entrada {
        Entrada(date: Date(), resumo: ResumoIlha(estado: .esperando, esperando: 2,
                                                 linha: "Rodar os testes?", agente: "Claude"))
    }

    func getSnapshot(in context: Context, completion: @escaping (Entrada) -> Void) {
        completion(context.isPreview ? placeholder(in: context) : atual())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<Entrada>) -> Void) {
        completion(Timeline(entries: [atual()], policy: .after(Date(timeIntervalSinceNow: 15 * 60))))
    }

    private func atual() -> Entrada {
        let r = UserDefaults(suiteName: Ilha.grupo).flatMap(Ilha.ler) ?? .vazio
        return Entrada(date: Date(), resumo: r)
    }
}

struct PainelWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "NoahPainel", provider: Provedor()) { e in
            PainelView(r: e.resumo)
                .containerBackground(for: .widget) { Color(.systemBackground) }
                .widgetURL(Atalho.para(e.resumo))
        }
        .configurationDisplayName("Noah")
        .description("O que espera você, o que está rodando e o que ficou pronto.")
        .supportedFamilies([.systemSmall, .systemMedium,
                            .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

struct PainelView: View {
    @Environment(\.widgetFamily) private var familia
    @Environment(\.widgetRenderingMode) private var modo
    var r: ResumoIlha

    var body: some View {
        switch familia {
        case .accessoryInline:
            Label(r.curto, systemImage: r.estado.simbolo)
        case .accessoryCircular:
            ZStack {
                AccessoryWidgetBackground()
                VStack(spacing: 1) {
                    Rosto(estado: r.estado, tamanho: 26, monocromatico: true)
                    if r.estado == .esperando { Text("\(r.esperando)").font(.caption2.bold()) }
                }
            }
        case .accessoryRectangular:
            HStack(spacing: 6) {
                Rosto(estado: r.estado, tamanho: 30, monocromatico: modo != .fullColor)
                VStack(alignment: .leading, spacing: 0) {
                    Text(r.estado.titulo).font(.headline).widgetAccentable()
                    Text(r.linha).font(.caption).lineLimit(2)
                }
            }
        case .systemMedium:
            HStack(spacing: 14) {
                Rosto(estado: r.estado, tamanho: 64)
                VStack(alignment: .leading, spacing: 4) {
                    Text(r.estado.titulo).font(.headline).foregroundStyle(r.estado.cor)
                    Text(r.linha).font(.subheadline).lineLimit(2)
                    if !r.agente.isEmpty { Text(r.agente).font(.caption).foregroundStyle(.secondary) }
                    Spacer(minLength: 0)
                    Contadores(r: r)
                }
                Spacer(minLength: 0)
            }
        default:
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Rosto(estado: r.estado, tamanho: 44)
                    Spacer()
                    if r.estado == .esperando {
                        Text("\(r.esperando)").font(.title.bold()).foregroundStyle(r.estado.cor)
                    }
                }
                Spacer(minLength: 0)
                Text(r.estado.titulo).font(.headline).foregroundStyle(r.estado.cor)
                Text(r.linha).font(.caption).lineLimit(2).foregroundStyle(.secondary)
            }
        }
    }
}

struct Contadores: View {
    var r: ResumoIlha
    var body: some View {
        HStack(spacing: 10) {
            Label("\(r.esperando)", systemImage: "exclamationmark.circle").foregroundStyle(EstadoIlha.esperando.cor)
            Label("\(r.rodando)", systemImage: "ellipsis.circle").foregroundStyle(EstadoIlha.trabalhando.cor)
            Label("\(r.prontas)", systemImage: "checkmark.circle").foregroundStyle(EstadoIlha.pronto.cor)
        }
        .font(.caption.bold())
        .labelStyle(.titleAndIcon)
    }
}

// MARK: - Live Activity (ilha dinâmica e tela bloqueada)

struct IlhaAoVivo: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: NoahAtributos.self) { contexto in
            TelaBloqueada(r: contexto.state)
                .activityBackgroundTint(.black.opacity(0.85))
                .activitySystemActionForegroundColor(.white)
                .widgetURL(Atalho.para(contexto.state))
        } dynamicIsland: { contexto in
            let r = contexto.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Rosto(estado: r.estado, tamanho: 44).padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    if r.estado == .esperando {
                        Text("\(r.esperando)").font(.title2.bold()).foregroundStyle(r.estado.corClara)
                    }
                }
                DynamicIslandExpandedRegion(.center) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.estado.titulo).font(.headline).foregroundStyle(r.estado.corClara)
                        Text(r.linha).font(.subheadline).lineLimit(2).foregroundStyle(.white)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    // Botões abrem o app: aprovar sempre passa pelo Face ID lá dentro.
                    HStack {
                        if r.estado == .esperando, let chave = r.chave {
                            Link(destination: Atalho.pendencia(chave)) {
                                Label("Ver e aprovar", systemImage: "faceid")
                                    .font(.subheadline.bold())
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 8)
                                    .background(Capsule().fill(r.estado.cor))
                                    .foregroundStyle(.black)
                            }
                        }
                        Link(destination: Atalho.fluxo) {
                            Label("Fluxo", systemImage: "waveform.path.ecg")
                                .font(.subheadline)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 8)
                                .background(Capsule().fill(.white.opacity(0.15)))
                                .foregroundStyle(.white)
                        }
                    }
                }
            } compactLeading: {
                Rosto(estado: r.estado, tamanho: 22)
            } compactTrailing: {
                Text(r.estado == .esperando ? "\(r.esperando)" : (r.estado == .pronto ? "✓" : "…"))
                    .font(.caption.bold())
                    .foregroundStyle(r.estado.corClara)
            } minimal: {
                Rosto(estado: r.estado, tamanho: 20)
            }
            .widgetURL(Atalho.para(r))
            .keylineTint(r.estado.cor)
        }
    }
}

struct TelaBloqueada: View {
    var r: ResumoIlha
    var body: some View {
        HStack(spacing: 12) {
            Rosto(estado: r.estado, tamanho: 48)
            VStack(alignment: .leading, spacing: 2) {
                Text(r.estado.titulo).font(.headline).foregroundStyle(r.estado.corClara)
                Text(r.linha).font(.subheadline).lineLimit(2).foregroundStyle(.white)
                if !r.agente.isEmpty {
                    Text(r.agente).font(.caption).foregroundStyle(.white.opacity(0.6))
                }
            }
            Spacer(minLength: 0)
            if r.estado == .esperando {
                Image(systemName: "faceid").font(.title2).foregroundStyle(r.estado.corClara)
            }
        }
        .padding(14)
    }
}
