import SwiftUI

struct DetailView: View {
    @EnvironmentObject var api: APIClient
    @Environment(\.openURL) private var openURL
    let mediaType: String
    let externalId: String
    let title: String

    @State private var detail: MediaItem?
    @State private var libraryEntry: MediaEntry?
    @State private var isLoading = true
    @State private var showRating = false
    @State private var selectedRating: Double = 7.0

    var body: some View {
        ScrollView {
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, minHeight: 600)
            } else if let detail {
                contentView(detail)
            }
        }
        .navigationTitle(title)
        .task { await loadDetail() }
    }

    @ViewBuilder
    private func contentView(_ item: MediaItem) -> some View {
        HStack(alignment: .top, spacing: 40) {
            AsyncImage(url: URL(string: item.imageUrl ?? "")) { image in
                image.resizable().aspectRatio(2/3, contentMode: .fit)
            } placeholder: {
                RoundedRectangle(cornerRadius: 12)
                    .fill(.quaternary)
                    .aspectRatio(2/3, contentMode: .fit)
            }
            .frame(width: 400)
            .cornerRadius(12)

            VStack(alignment: .leading, spacing: 20) {
                Text(item.title)
                    .font(.title)
                    .bold()

                HStack(spacing: 16) {
                    if let year = item.year {
                        Text(String(year)).foregroundStyle(.secondary)
                    }
                    if let creator = item.creator {
                        Text(creator).foregroundStyle(.secondary)
                    }
                }

                if let genres = item.genres {
                    Text(genres)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }

                if let desc = item.description {
                    Text(desc)
                        .lineLimit(8)
                        .foregroundStyle(.secondary)
                }

                if let reason = item.reason {
                    Text(reason)
                        .italic()
                        .foregroundStyle(.blue)
                }

                Spacer().frame(height: 10)

                // Streaming links
                if let providers = item.watchProviders, !providers.isEmpty {
                    streamingSection(item: item, providers: providers)
                }

                Spacer().frame(height: 10)

                // Library actions
                HStack(spacing: 20) {
                    if libraryEntry != nil {
                        Label("In Library", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    } else {
                        Button {
                            Task { await markConsumed() }
                        } label: {
                            Label("Mark Watched", systemImage: "eye")
                        }
                    }

                    Button {
                        showRating = true
                    } label: {
                        if let rating = libraryEntry?.rating {
                            Label("\(rating, specifier: "%.0f")/10", systemImage: "star.fill")
                        } else {
                            Label("Rate", systemImage: "star")
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(60)
        .sheet(isPresented: $showRating) {
            RatingSheet(
                title: item.title,
                currentRating: libraryEntry?.rating ?? 7.0,
                onSave: { rating in
                    Task { await submitRating(rating) }
                }
            )
        }
    }

    private func streamingSection(item: MediaItem, providers: [WatchProvider]) -> some View {
        let links = StreamingLinks.links(
            for: providers,
            title: item.title,
            mediaType: item.mediaType,
            externalId: item.externalId
        )

        return VStack(alignment: .leading, spacing: 12) {
            Text("Watch Now")
                .font(.headline)

            if links.isEmpty {
                Text("Available on: \(providers.map(\.name).joined(separator: ", "))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 16) {
                        ForEach(links, id: \.name) { link in
                            Button {
                                openURL(link.url)
                            } label: {
                                HStack(spacing: 8) {
                                    if let logoUrl = link.logoUrl {
                                        AsyncImage(url: URL(string: logoUrl)) { image in
                                            image.resizable()
                                        } placeholder: {
                                            Color.clear
                                        }
                                        .frame(width: 32, height: 32)
                                        .cornerRadius(6)
                                    }

                                    Text(link.name)
                                        .font(.caption)
                                        .lineLimit(1)
                                }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                            }
                        }
                    }
                }
            }
        }
    }

    private func loadDetail() async {
        isLoading = true
        do {
            detail = try await api.request(.mediaDetail(mediaType: mediaType, externalId: externalId))
            let lib: [MediaEntry] = try await api.request(.library())
            libraryEntry = lib.first { $0.externalId == externalId }
        } catch {
            print("DetailView loadDetail error: \(error)")
            detail = nil
        }
        isLoading = false
    }

    private func markConsumed() async {
        guard let detail else { return }
        let entry = CreateEntryRequest(
            externalId: detail.externalId,
            source: detail.source ?? "tmdb",
            title: detail.title,
            mediaType: detail.mediaType,
            imageUrl: detail.imageUrl,
            year: detail.year,
            creator: detail.creator,
            genres: detail.genres,
            description: detail.description,
            status: "consumed",
            rating: nil
        )
        do {
            let created: MediaEntry = try await api.request(.createEntry(entry))
            libraryEntry = created
        } catch {}
    }

    private func submitRating(_ rating: Double) async {
        if let existing = libraryEntry {
            let updates = UpdateEntryRequest(status: nil, rating: rating, notes: nil)
            do {
                let updated: MediaEntry = try await api.request(.updateEntry(id: existing.id, updates: updates))
                libraryEntry = updated
            } catch {}
        } else {
            guard let detail else { return }
            let entry = CreateEntryRequest(
                externalId: detail.externalId,
                source: detail.source ?? "tmdb",
                title: detail.title,
                mediaType: detail.mediaType,
                imageUrl: detail.imageUrl,
                year: detail.year,
                creator: detail.creator,
                genres: detail.genres,
                description: detail.description,
                status: "consumed",
                rating: rating
            )
            do {
                let created: MediaEntry = try await api.request(.createEntry(entry))
                libraryEntry = created
            } catch {}
        }
    }
}

struct RatingSheet: View {
    let title: String
    @State var currentRating: Double
    let onSave: (Double) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 30) {
            Text("Rate \(title)")
                .font(.title2)
                .bold()

            RatingStepper(value: $currentRating)

            HStack(spacing: 30) {
                Button("Cancel") { dismiss() }
                Button("Save") {
                    onSave(currentRating)
                    dismiss()
                }
                .bold()
            }
        }
        .padding(40)
    }
}
