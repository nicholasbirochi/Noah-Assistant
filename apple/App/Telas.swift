import NoahCore
import SwiftUI
import UserNotifications
#if os(macOS)
import ServiceManagement
#endif

struct ContentView: View {
    @Environment(Modelo.self) private var modelo

    var body: some View {
        @Bindable var modelo = modelo
        TabView(selection: $modelo.aba) {
            PendenciasView()
                .tabItem { Label("Pendências", systemImage: "tray.full") }
                .badge(modelo.contagem)
                .tag(Aba.pendencias)
            FluxoView()
                .tabItem { Label("Fluxo", systemImage: "point.3.connected.trianglepath.dotted") }
                .tag(Aba.fluxo)
            PresencaView()
                .tabItem { Label("Presença", systemImage: "eye") }
                .tag(Aba.presenca)
            AjustesView()
                .tabItem { Label("Ajustes", systemImage: "gearshape") }
                .tag(Aba.ajustes)
        }
        .overlay(alignment: .bottom) {
            if let aviso = modelo.aviso {
                Text(aviso)
                    .font(.callout)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(.thinMaterial, in: Capsule())
                    .padding(.bottom, 64)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.default, value: modelo.aviso)
        .onChange(of: modelo.aba) { _, aba in
            if aba == .presenca { Task { await modelo.atualizarPresenca() } }
            if aba == .fluxo { Task { await modelo.atualizarCerebro() } }
        }
    }
}

// MARK: - Pendências

/// Tela inicial: só as tarefas, curtas. Tocar abre o detalhe; o painel
/// lateral "Ao vivo" mostra o que muda a cada atualização (aberto por padrão
/// no Mac; no iPhone, pelo botão da barra).
struct PendenciasView: View {
    @Environment(Modelo.self) private var modelo
    // No Mac lembra se o painel estava aberto (começa aberto); no iPhone é uma folha.
    #if os(macOS)
    @AppStorage("aoVivo") private var aoVivo = true
    #else
    @State private var aoVivo = false
    #endif

    var body: some View {
        @Bindable var modelo = modelo
        NavigationSplitView {
            ListaTarefas()
                #if os(macOS)
                .navigationSplitViewColumnWidth(min: 260, ideal: 300)
                #endif
                .toolbar {
                    ToolbarItem {
                        Button {
                            Task {
                                await modelo.atualizar()
                                if modelo.erro == nil { modelo.mostrar("Atualizado") }
                            }
                        } label: {
                            Label("Atualizar", systemImage: "arrow.clockwise")
                        }
                    }
                    ToolbarItem {
                        Button { aoVivo.toggle() } label: {
                            Label("Ao vivo", systemImage: "dot.radiowaves.left.and.right")
                        }
                        .help("Mostra ou esconde o painel Ao vivo")
                    }
                }
        } detail: {
            // No Mac o painel é uma coluna fixa à direita (o `.inspector` dentro
            // do TabView entra em laço de layout no AppKit e derruba o app).
            HStack(spacing: 0) {
                detalhe
                #if os(macOS)
                if aoVivo {
                    Divider()
                    PainelAoVivo().frame(width: 280)
                }
                #endif
            }
        }
        #if os(iOS)
        .sheet(isPresented: $aoVivo) {
            NavigationStack {
                PainelAoVivo()
                    .navigationTitle("Ao vivo")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar { Button("OK") { aoVivo = false } }
            }
            .presentationDetents([.medium, .large])
        }
        #endif
    }

    @ViewBuilder private var detalhe: some View {
        if let chave = modelo.selecionada {
            PendenciaDetalhe(chave: chave)
        } else {
            ContentUnavailableView("Escolha uma tarefa", systemImage: "hand.tap",
                                   description: Text("Toque numa tarefa para ver o detalhe e responder."))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

struct ListaTarefas: View {
    @Environment(Modelo.self) private var modelo

    var body: some View {
        @Bindable var modelo = modelo
        let (conversas, automaticas) = Pendencia.separar(modelo.itens)
        List(selection: $modelo.selecionada) {
            if let erro = modelo.erro {
                Label("Não deu para atualizar: \(erro)", systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            }
            ForEach(modelo.falhas, id: \.self) { falha in
                Label("Fonte com problema (pulada): \(falha)", systemImage: "exclamationmark.circle")
                    .foregroundStyle(.orange)
            }
            if !modelo.jobsVisiveis.isEmpty {
                Section("Respostas") {
                    ForEach(modelo.jobsVisiveis) { JobLinha(job: $0) }
                }
            }
            if !conversas.isEmpty {
                Section("Para fazer") {
                    ForEach(conversas) { TarefaLinha(p: $0).tag($0.chave) }
                }
            }
            if !automaticas.isEmpty {
                Section {
                    ForEach(automaticas) { TarefaLinha(p: $0).tag($0.chave) }
                } header: {
                    Text("Geradas automaticamente")
                } footer: {
                    Text("O Noah cria estas sozinho, a partir da Presença. Toque para ver o porquê.")
                }
            }
        }
        .overlay {
            if modelo.itens.isEmpty && modelo.erro == nil && modelo.jobsVisiveis.isEmpty {
                ContentUnavailableView(
                    "Nada esperando você", systemImage: "checkmark.circle",
                    description: Text("Quando uma conversa terminar ou o Noah gerar uma tarefa, ela aparece aqui."))
            }
        }
        .refreshable { await modelo.atualizar() }
        .navigationTitle("Pendências")
    }
}

enum Visual {
    static func icone(_ fonte: String) -> String {
        ["claude": "bubble.left.and.text.bubble.right", "codex": "terminal", "noah": "wand.and.stars"][fonte]
            ?? "tray"
    }

    static func icone(_ tipo: Evento.Tipo) -> (String, Color) {
        switch tipo {
        case .nova: ("plus.circle.fill", .blue)
        case .resolvida: ("checkmark.circle.fill", .green)
        case .respondendo: ("ellipsis.bubble.fill", .orange)
        case .respondeu: ("checkmark.bubble.fill", .green)
        case .falhou: ("exclamationmark.triangle.fill", .red)
        }
    }

    static func meta(_ p: Pendencia) -> String {
        let partes = p.automatica
            ? ["Noah", p.titulo]
            : [Fonte.nome(p.fonte), p.projeto, p.quando.isEmpty ? "" : Sincronia.haQuanto(p.quando)]
        return partes.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

/// Uma linha curta: o que fazer e de onde veio.
struct TarefaLinha: View {
    let p: Pendencia

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: Visual.icone(p.fonte))
                .foregroundStyle(p.automatica ? Color.purple : Color.accentColor)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(p.tarefa).lineLimit(2)
                Text(Visual.meta(p)).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            if p.respondendo { ProgressView().controlSize(.small) }
        }
        .padding(.vertical, 2)
    }
}

struct JobLinha: View {
    let job: Job

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                if job.rodando { ProgressView().controlSize(.small) }
                Text(job.titulo).font(.subheadline.weight(.medium))
            }
            Text("\(Fonte.nome(job.fonte)) \(job.rotuloEstado)")
                .font(.caption)
                .foregroundStyle(job.estado == "erro" ? .red : .secondary)
            if job.estado == "erro", let detalhe = job.detalhe, !detalhe.isEmpty {
                Text(detalhe).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// Tudo sobre uma pendência. Segue a lista viva pela chave: se ela for
/// resolvida no outro aparelho, o detalhe diz isso em vez de mostrar dado velho.
struct PendenciaDetalhe: View {
    @Environment(Modelo.self) private var modelo
    let chave: String

    var body: some View {
        if let p = modelo.item(chave) {
            Conteudo(p: p)
        } else {
            ContentUnavailableView("Já saiu da lista", systemImage: "checkmark.circle",
                                   description: Text("Foi respondida ou dispensada, aqui ou no outro aparelho."))
        }
    }

    struct Conteudo: View {
        @Environment(Modelo.self) private var modelo
        let p: Pendencia

        private var rascunho: Binding<String> {
            Binding(get: { modelo.rascunhos[p.chave] ?? "" },
                    set: { modelo.rascunhos[p.chave] = $0 })
        }

        private var ocupado: Bool { modelo.enviando.contains(p.chave) }

        var body: some View {
            Form {
                Section {
                    Text(p.tarefa).font(.title3.weight(.semibold)).textSelection(.enabled)
                    Label(p.origem, systemImage: p.automatica ? "wand.and.stars" : Visual.icone(p.fonte))
                        .font(.subheadline)
                        .foregroundStyle(p.automatica ? Color.purple : Color.secondary)
                }

                if let acao = p.acao {
                    Section("O que fazer") {
                        Text(acao).textSelection(.enabled)
                    }
                }

                if !p.motivo.isEmpty {
                    Section(p.automatica ? "Por quê" : "Última mensagem") {
                        Text(p.motivo).textSelection(.enabled)
                    }
                }

                Section("Detalhes") {
                    LabeledContent("Origem", value: p.automatica ? "Automática (Noah)" : "Conversa (\(Fonte.nome(p.fonte)))")
                    if p.automatica { LabeledContent("Gerada por", value: p.titulo) }
                    if !p.projeto.isEmpty { LabeledContent("Projeto", value: p.projeto) }
                    if !p.quando.isEmpty { LabeledContent("Quando", value: Sincronia.haQuanto(p.quando)) }
                    LabeledContent("Resposta", value: p.podeResponder ? "Pelo app ou pelo aviso" : "Só leitura")
                }

                Section {
                    if p.respondendo {
                        Label("\(Fonte.nome(p.fonte)) está respondendo…", systemImage: "ellipsis.bubble")
                            .foregroundStyle(.secondary)
                    } else if p.podeResponder {
                        TextField("Sua resposta", text: rascunho, axis: .vertical)
                            .lineLimit(2...8)
                            .disabled(ocupado)
                        Button("Enviar") {
                            let texto = rascunho.wrappedValue
                            Task { await modelo.responder(p, texto: texto) }
                        }
                        .disabled(ocupado || rascunho.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        Button("Aceitar (“\(Ajustes.respostaAceitar)”)") { Task { await modelo.aceitar(p) } }
                            .disabled(ocupado)
                    }
                    Button("Dispensar", role: .destructive) { Task { await modelo.dispensar(p) } }
                        .disabled(ocupado)
                } header: {
                    Text(p.podeResponder ? "Responder" : "Ação")
                } footer: {
                    Text("Vale para os dois aparelhos: o que você faz aqui some do outro na próxima atualização.")
                }
            }
            .formStyle(.grouped)
            .navigationTitle(Fonte.nome(p.fonte))
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
        }
    }
}

/// Painel lateral: o pulso da central, quem está respondendo e o que mudou.
struct PainelAoVivo: View {
    @Environment(Modelo.self) private var modelo

    var body: some View {
        let (conversas, automaticas) = Pendencia.separar(modelo.itens)
        let rodando = modelo.jobs.filter(\.rodando)
        List {
            Section {
                TimelineView(.periodic(from: .now, by: 1)) { ctx in
                    HStack(spacing: 8) {
                        Circle()
                            .fill(modelo.erro == nil ? Color.green : Color.red)
                            .frame(width: 8, height: 8)
                        Text(pulso(ctx.date)).font(.callout)
                    }
                }
                LabeledContent("Para fazer", value: "\(conversas.filter { !$0.respondendo }.count)")
                LabeledContent("Geradas pelo Noah", value: "\(automaticas.count)")
                LabeledContent("Respondendo agora", value: "\(rodando.count)")
            } header: {
                Text("Ao vivo")
            }

            if !rodando.isEmpty {
                Section("Respondendo") {
                    ForEach(rodando) { j in
                        HStack {
                            ProgressView().controlSize(.small)
                            Text("\(Fonte.nome(j.fonte)): \(j.titulo)").font(.callout).lineLimit(2)
                        }
                    }
                }
            }

            Section {
                if modelo.atividade.isEmpty {
                    Text("Nada mudou desde que o app abriu.").font(.callout).foregroundStyle(.secondary)
                }
                ForEach(modelo.atividade) { ev in
                    let (simbolo, cor) = Visual.icone(ev.tipo)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: simbolo).foregroundStyle(cor)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(ev.texto).font(.callout).lineLimit(3)
                            Text(ev.quando.formatted(date: .omitted, time: .standard))
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            } header: {
                Text("Atividade")
            }
        }
        .animation(.default, value: modelo.atividade)
    }

    private func pulso(_ agora: Date) -> String {
        guard let quando = modelo.atualizadoEm else { return modelo.erro == nil ? "Conectando…" : "Sem conexão" }
        let s = max(0, Int(agora.timeIntervalSince(quando)))
        let base = modelo.erro == nil ? "Sincronizado" : "Sem conexão; última leitura"
        return s < 2 ? "\(base) agora" : "\(base) há \(s) s"
    }
}

// MARK: - Presença

struct PresencaView: View {
    @Environment(Modelo.self) private var modelo

    var body: some View {
        NavigationStack {
            Group {
                if let erro = modelo.erroPresenca {
                    ContentUnavailableView("Não deu para atualizar", systemImage: "exclamationmark.triangle",
                                           description: Text(erro))
                } else if let estado = modelo.presenca {
                    if !estado.ligada {
                        ContentUnavailableView(
                            "Presença desligada", systemImage: "eye.slash",
                            description: Text("Enquanto estiver desligada, nada é contado. Para ligar, ponha `\(estado.variavel)=true` no .env do Noah e abra o app de novo com `python src/cli.py central`."))
                    } else if estado.itens.isEmpty && estado.falhas.isEmpty {
                        ContentUnavailableView(
                            "Nada agora", systemImage: "sparkles",
                            description: Text("Quando algo pedir sua atenção (propostas, conflitos, lembretes), aparece aqui."))
                    } else {
                        List {
                            ForEach(estado.falhas, id: \.self) { falha in
                                Label("Fonte com problema (pulada): \(falha)", systemImage: "exclamationmark.circle")
                                    .foregroundStyle(.orange)
                            }
                            ForEach(estado.itens, id: \.self) { item in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(item.source).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                                    Text(item.why)
                                    Text("O que fazer").font(.caption.weight(.semibold)).padding(.top, 2)
                                    Text(item.action).font(.subheadline)
                                }
                                .padding(.vertical, 4)
                            }
                        }
                    }
                } else {
                    ProgressView()
                }
            }
            .refreshable { await modelo.atualizarPresenca() }
            .navigationTitle("Presença")
            .toolbar {
                ToolbarItem {
                    Button {
                        Task { await modelo.atualizarPresenca() }
                    } label: {
                        Label("Atualizar", systemImage: "arrow.clockwise")
                    }
                }
                ToolbarItem(placement: .status) {
                    Text("Só leitura").font(.caption).foregroundStyle(.secondary)
                }
            }
            .task { await modelo.atualizarPresenca() }
        }
    }
}

// MARK: - Ajustes

struct AjustesView: View {
    @Environment(Modelo.self) private var modelo
    @State private var endereco = Ajustes.endereco
    @State private var token = Cofre.ler() ?? ""
    @State private var aceitar = Ajustes.respostaAceitar
    @State private var resultado: String?
    @State private var testando = false
    #if os(macOS)
    @State private var abrirAoIniciar = SMAppService.mainApp.status == .enabled
    #endif

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Endereço", text: $endereco, prompt: Text(Ajustes.enderecoPadrao))
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif
                    SecureField("Token", text: $token, prompt: Text("vazio se a central não pede"))
                    Button(testando ? "Testando…" : "Salvar e testar") { Task { await salvar() } }
                        .disabled(testando)
                    if let resultado { Text(resultado).font(.callout) }
                } header: {
                    Text("Central")
                } footer: {
                    // Com --host <IP> a central só atende naquele IP: o Mac também
                    // precisa do endereço da rede, senão os dois não se falam.
                    Text("Só no Mac: \(Ajustes.enderecoPadrao), sem token. Com o iPhone junto, abra a central no Mac com `python src/cli.py central --host \"$(ipconfig getifaddr en0)\" --token SEU_TOKEN` e ponha http://IP-DO-MAC:8769 e o mesmo token nos dois aparelhos, inclusive no Mac. Os dois leem a mesma central: o que você responde ou dispensa num some do outro.")
                }

                Section {
                    TextField("Resposta", text: $aceitar, prompt: Text(RespostaRapida.aceitar))
                        .onSubmit { Ajustes.respostaAceitar = aceitar }
                } header: {
                    Text("Botão Aceitar")
                } footer: {
                    Text("O texto que o botão Aceitar envia, no app e no aviso.")
                }

                Section {
                    LabeledContent("Avisos", value: modelo.permissao.rotulo)
                    if modelo.permissao == .desconhecida || modelo.permissao == .naoPedida {
                        Button("Permitir avisos") { Task { await modelo.pedirPermissao() } }
                    }
                } header: {
                    Text("Avisos")
                } footer: {
                    #if os(iOS)
                    Text("Cada pendência nova vira um aviso com Responder, Aceitar e Dispensar. Com o app aberto ou usado há pouco, chega em segundos. Fechado, depende do iOS acordar o app de tempos em tempos (sem conta paga da Apple não há push).")
                    #else
                    Text("Cada pendência nova vira um aviso com Responder, Aceitar e Dispensar. O Noah fica na barra de menus mesmo com a janela fechada.")
                    #endif
                }

                #if os(macOS)
                Section {
                    Toggle("Abrir ao iniciar sessão", isOn: $abrirAoIniciar)
                        .onChange(of: abrirAoIniciar) { _, ligar in
                            do {
                                if ligar { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                            } catch {
                                resultado = "Não deu para mudar: \(error.localizedDescription)"
                                abrirAoIniciar = SMAppService.mainApp.status == .enabled
                            }
                        }
                }
                #endif
            }
            .formStyle(.grouped)
            .navigationTitle("Ajustes")
            .task { await modelo.lerPermissao() }
            .onDisappear { Ajustes.respostaAceitar = aceitar }
        }
    }

    private func salvar() async {
        testando = true
        defer { testando = false }
        Ajustes.endereco = endereco.trimmingCharacters(in: .whitespacesAndNewlines)
        Cofre.gravar(token.trimmingCharacters(in: .whitespacesAndNewlines))
        Ajustes.respostaAceitar = aceitar
        await modelo.atualizar()
        resultado = modelo.erro.map { "Não conectou: \($0)" } ?? "Conectado. \(modelo.itens.count) pendência(s)."
    }
}

enum UNAuthorizationStatusTexto: Equatable {
    case desconhecida, naoPedida, negada, permitida

    init(_ status: UNAuthorizationStatus) {
        switch status {
        case .notDetermined: self = .naoPedida
        case .denied: self = .negada
        case .authorized, .provisional, .ephemeral: self = .permitida
        @unknown default: self = .desconhecida
        }
    }

    var rotulo: String {
        switch self {
        case .desconhecida: "…"
        case .naoPedida: "Ainda não pedidos"
        #if os(iOS)
        case .negada: "Bloqueados: ligue em Ajustes › Noah › Notificações"
        #else
        case .negada: "Bloqueados: ligue em Ajustes do Sistema › Notificações › Noah"
        #endif
        case .permitida: "Ligados"
        }
    }
}
