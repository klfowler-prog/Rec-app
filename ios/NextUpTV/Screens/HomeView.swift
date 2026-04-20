import SwiftUI

@MainActor
final class HomeViewModel: ObservableObject {
    @Published var bundle: HomeBundle?
    @Published var trending: [MediaItem] = []
    @Published var isLoading = true
    @Published var error: String?
    private var hasLoaded = false

    func loadIfNeeded(api: APIClient) async {
        guard !hasLoaded else { return }
        await load(api: api)
    }

    func refresh(api: APIClient) async {
        await load(api: api)
    }

    private func load(api: APIClient) async {
        isLoading = true
        error = nil
        do {
            bundle = try await api.request(.homeBundle())
            trending = try await api.request(.trending(mediaType: "movie"))
            hasLoaded = true
        } catch {
            print("HomeView loadData error: \(error)")
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}

struct HomeView: View {
    @EnvironmentObject var api: APIClient
    @StateObject private var vm = HomeViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Theme.Spacing.rowGap) {
                    if vm.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity, minHeight: 400)
                    } else if let error = vm.error {
                        errorView(error)
                    } else {
                        // Tonight hero — above everything
                        if let tonight = vm.bundle?.tonight {
                            TonightHero(pick: tonight)
                        }

                        if let picks = vm.bundle?.topPicks, !picks.isEmpty {
                            mediaRow(title: "Top Picks for You",
                                     eyebrow: "Strongest signal · tonight",
                                     items: picks)
                        }

                        if let suggestions = vm.bundle?.suggestions {
                            suggestionsSection(suggestions)
                        }

                        if !vm.trending.isEmpty {
                            mediaRow(title: "Trending", items: vm.trending)
                        }

                        if let themes = vm.bundle?.themes {
                            ForEach(Array(themes.keys.sorted()), id: \.self) { key in
                                if let items = themes[key], !items.isEmpty {
                                    mediaRow(title: key, items: items)
                                }
                            }
                        }

                        if let insights = vm.bundle?.insights, !insights.isEmpty {
                            insightsSection(insights)
                        }
                    }
                }
                .padding(.vertical, 40)
            }
            .background(Theme.bg)
            .navigationTitle("NextUp")
            .navigationDestination(for: MediaItem.self) { item in
                DetailView(mediaType: item.mediaType, externalId: item.externalId, title: item.title)
            }
            .toolbar {
                ToolbarItem(placement: .automatic) {
                    Button {
                        Task { await vm.refresh(api: api) }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .task { await vm.loadIfNeeded(api: api) }
        }
    }

    private func mediaRow(title: String, eyebrow: String? = nil, items: [MediaItem]) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                if let eyebrow { Eyebrow(text: eyebrow) }
                Text(title)
                    .font(.system(size: Theme.FontSize.rowTitle, weight: .bold))
                    .foregroundStyle(Theme.ink)
            }
            .padding(.horizontal, Theme.Spacing.screenPadding)

            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: Theme.Spacing.posterGap) {
                    ForEach(items) { item in
                        NavigationLink(value: item) {
                            PosterCard(item: item)
                        }
                        .buttonStyle(.card)
                    }
                }
                .padding(.horizontal, Theme.Spacing.screenPadding)
            }
        }
    }

    private func suggestionsSection(_ suggestions: HomeSuggestions) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Suggestions")
                .font(.system(size: Theme.FontSize.rowTitle, weight: .bold))
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, Theme.Spacing.screenPadding)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: Theme.Spacing.posterGap) {
                    if let pick = suggestions.quickPick {
                        suggestionCard(label: "Quick Pick", item: pick)
                    }
                    if let deep = suggestions.deepDive {
                        suggestionCard(label: "Deep Dive", item: deep)
                    }
                    if let wild = suggestions.wildcard {
                        suggestionCard(label: "Wildcard", item: wild)
                    }
                }
                .padding(.horizontal, Theme.Spacing.screenPadding)
            }
        }
    }

    private func suggestionCard(label: String, item: MediaItem) -> some View {
        NavigationLink(value: item) {
            VStack(alignment: .leading, spacing: 8) {
                Eyebrow(text: label)
                PosterCard(item: item)
            }
        }
        .buttonStyle(.card)
    }

    private func insightsSection(_ insights: [Insight]) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Taste Insights")
                .font(.system(size: Theme.FontSize.rowTitle, weight: .bold))
                .foregroundStyle(Theme.ink)

            ForEach(insights, id: \.self) { insight in
                Text(insight.text)
                    .foregroundStyle(Theme.inkDim)
            }
        }
        .padding(.horizontal, Theme.Spacing.screenPadding)
    }

    private func errorView(_ message: String) -> some View {
        VStack(spacing: 16) {
            Text(message).foregroundStyle(Theme.inkDim)
            Button("Retry") { Task { await vm.refresh(api: api) } }
                .tint(Theme.gold)
        }
        .frame(maxWidth: .infinity, minHeight: 400)
    }
}
