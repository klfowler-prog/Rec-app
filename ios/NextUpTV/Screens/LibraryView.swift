import SwiftUI

struct LibraryView: View {
    @EnvironmentObject var api: APIClient
    @State private var entries: [MediaEntry] = []
    @State private var isLoading = true
    @State private var selectedType: String? = nil
    @State private var error: String?

    private let mediaTypes = [
        ("All", nil as String?),
        ("Movies", "movie" as String?),
        ("TV", "tv" as String?),
        ("Books", "book" as String?),
        ("Podcasts", "podcast" as String?),
    ]

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 0) {
                // Type filter
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 16) {
                        ForEach(mediaTypes, id: \.0) { label, type in
                            Button(label) { selectedType = type }
                                .buttonStyle(.bordered)
                                .tint(selectedType == type ? .blue : .gray)
                        }
                    }
                    .padding(.horizontal, 60)
                    .padding(.vertical, 20)
                }

                if isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity, minHeight: 400)
                } else if entries.isEmpty {
                    Text("Nothing here yet.")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 400)
                } else {
                    ScrollView {
                        LazyVGrid(
                            columns: [GridItem(.adaptive(minimum: 200), spacing: 24)],
                            spacing: 24
                        ) {
                            ForEach(filteredEntries) { entry in
                                NavigationLink(value: entry) {
                                    libraryCard(entry)
                                }
                                .buttonStyle(.card)
                            }
                        }
                        .padding(.horizontal, 60)
                        .padding(.vertical, 20)
                    }
                }
            }
            .navigationTitle("Library")
            .navigationDestination(for: MediaEntry.self) { entry in
                DetailView(mediaType: entry.mediaType, externalId: entry.externalId, title: entry.title)
            }
            .task { await loadLibrary() }
            .refreshable { await loadLibrary() }
            .onChange(of: selectedType) { _, _ in
                Task { await loadLibrary() }
            }
        }
    }

    private var filteredEntries: [MediaEntry] {
        guard let type = selectedType else { return entries }
        return entries.filter { $0.mediaType == type }
    }

    private func libraryCard(_ entry: MediaEntry) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            AsyncImage(url: URL(string: entry.imageUrl ?? "")) { image in
                image.resizable().aspectRatio(2/3, contentMode: .fill)
            } placeholder: {
                RoundedRectangle(cornerRadius: 8)
                    .fill(.quaternary)
                    .aspectRatio(2/3, contentMode: .fill)
            }
            .frame(width: 200, height: 300)
            .cornerRadius(8)

            Text(entry.title)
                .font(.caption)
                .lineLimit(2)

            if let rating = entry.rating {
                HStack(spacing: 2) {
                    Image(systemName: "star.fill")
                        .font(.caption2)
                        .foregroundStyle(.yellow)
                    Text("\(rating, specifier: "%.0f")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(width: 200)
    }

    private func loadLibrary() async {
        isLoading = true
        do {
            entries = try await api.request(.library(mediaType: selectedType))
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}
