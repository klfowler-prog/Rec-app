import SwiftUI

struct TogetherView: View {
    @EnvironmentObject var api: APIClient
    @State private var users: [TogetherUser] = []
    @State private var selectedUser: TogetherUser?
    @State private var comparison: CompareResult?
    @State private var isLoadingUsers = true
    @State private var isComparing = false

    var body: some View {
        NavigationStack {
            HStack(alignment: .top, spacing: 0) {
                ScrollView {
                    LazyVStack(spacing: 12) {
                        if isLoadingUsers {
                            ProgressView()
                                .padding(.top, 60)
                        } else if users.isEmpty {
                            Text("No friends yet")
                                .foregroundStyle(.secondary)
                                .padding(.top, 60)
                        } else {
                            ForEach(users) { user in
                                Button {
                                    selectedUser = user
                                    Task { await compare(with: user) }
                                } label: {
                                    HStack(spacing: 12) {
                                        AsyncImage(url: URL(string: user.picture ?? "")) { image in
                                            image.resizable()
                                        } placeholder: {
                                            Circle().fill(.quaternary)
                                        }
                                        .frame(width: 48, height: 48)
                                        .clipShape(Circle())

                                        Text(user.name)
                                            .lineLimit(1)

                                        Spacer()

                                        if selectedUser?.id == user.id {
                                            Image(systemName: "chevron.right")
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.vertical, 10)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                    .padding(.horizontal, 40)
                    .padding(.top, 20)
                }
                .frame(width: 400)

                Divider()

                ScrollView {
                    if isComparing {
                        ProgressView()
                            .frame(maxWidth: .infinity, minHeight: 400)
                    } else if let comparison, let other = selectedUser {
                        comparisonView(comparison, otherName: other.name)
                    } else {
                        Text("Select a friend to compare taste")
                            .foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, minHeight: 400)
                    }
                }
            }
            .navigationTitle("Together")
            .navigationDestination(for: MediaItem.self) { item in
                DetailView(mediaType: item.mediaType, externalId: item.externalId, title: item.title)
            }
            .task { await loadUsers() }
        }
    }

    private func comparisonView(_ result: CompareResult, otherName: String) -> some View {
        VStack(alignment: .leading, spacing: 32) {
            Text("You & \(otherName)")
                .font(.title2)
                .bold()

            if let genres = result.sharedGenres, !genres.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Shared genres")
                        .font(.headline)
                    Text(genres.joined(separator: ", "))
                        .foregroundStyle(.secondary)
                }
            }

            if let loved = result.sharedLoved, !loved.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("You both loved")
                        .font(.headline)
                    ForEach(loved, id: \.self) { item in
                        HStack {
                            Text(item.title)
                            Spacer()
                            if let my = item.myRating, let their = item.theirRating {
                                Text("\(my, specifier: "%.0f") / \(their, specifier: "%.0f")")
                                    .foregroundStyle(.secondary)
                                    .font(.caption)
                            }
                        }
                    }
                }
            }

            if let pick = result.watchTogether {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Watch Together")
                        .font(.headline)

                    NavigationLink(value: pick) {
                        HStack(spacing: 16) {
                            AsyncImage(url: URL(string: pick.imageUrl ?? "")) { image in
                                image.resizable().aspectRatio(2/3, contentMode: .fill)
                            } placeholder: {
                                RoundedRectangle(cornerRadius: 8).fill(.quaternary)
                            }
                            .frame(width: 120, height: 180)
                            .cornerRadius(8)

                            VStack(alignment: .leading, spacing: 8) {
                                Text(pick.title).font(.headline)
                                if let reason = pick.reason {
                                    Text(reason)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(4)
                                }
                            }
                        }
                    }
                    .buttonStyle(.card)
                }
            }

            if let candidates = result.candidates, !candidates.isEmpty {
                VStack(alignment: .leading, spacing: 16) {
                    Text("More Ideas")
                        .font(.headline)

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 20) {
                            ForEach(candidates) { item in
                                NavigationLink(value: item) {
                                    PosterCard(item: item)
                                }
                                .buttonStyle(.card)
                            }
                        }
                    }
                }
            }
        }
        .padding(40)
    }

    private func loadUsers() async {
        isLoadingUsers = true
        do {
            users = try await api.request(.togetherUsers())
        } catch {
            print("Together loadUsers error: \(error)")
        }
        isLoadingUsers = false
    }

    private func compare(with user: TogetherUser) async {
        isComparing = true
        do {
            comparison = try await api.request(.compare(otherUserId: user.id))
        } catch {
            print("Together compare error: \(error)")
        }
        isComparing = false
    }
}
