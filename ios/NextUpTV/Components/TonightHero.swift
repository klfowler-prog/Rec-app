import SwiftUI

/// The defining Navy-theme screen element: one confident editorial pick
/// at the top of Home, with a human-voiced reason + Watch / Details CTAs.
struct TonightHero: View {
    let pick: TonightPick
    var onWatch: () -> Void = {}

    var body: some View {
        HStack(alignment: .top, spacing: 60) {
            // LEFT — copy + CTAs
            VStack(alignment: .leading, spacing: 24) {
                Eyebrow(text: "Tonight · Your Signal Says")

                HStack(spacing: 16) {
                    SignalBadge(value: pick.item.signalScore ?? 0, size: .regular)
                    Text(pick.item.year.map { String($0) } ?? "")
                        .font(.system(size: 22))
                        .foregroundStyle(Theme.inkFaint)
                }

                Text(pick.item.title)
                    .font(.system(size: Theme.FontSize.heroTitle, weight: .bold))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                    .minimumScaleFactor(0.6)

                Text(pick.reason)
                    .font(.system(size: 26))
                    .foregroundStyle(Theme.inkDim)
                    .lineLimit(3)
                    .frame(maxWidth: 720, alignment: .leading)

                HStack(spacing: 16) {
                    Button(action: onWatch) {
                        Label(
                            "Watch on \(pick.providers.first ?? "Prime")",
                            systemImage: "play.fill"
                        )
                        .font(.system(size: 24, weight: .semibold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.gold)

                    NavigationLink(value: pick.item) {
                        Text("Details")
                            .font(.system(size: 24, weight: .medium))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                    }
                    .buttonStyle(.bordered)

                    Button {
                        // TODO: queue
                    } label: {
                        Label("Queue", systemImage: "plus")
                            .font(.system(size: 24, weight: .medium))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                    }
                    .buttonStyle(.bordered)
                }
                .padding(.top, 8)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // RIGHT — poster
            PosterCard(item: pick.item, width: 360, showTitle: false, showSignal: false)
                .shadow(color: .black.opacity(0.5), radius: 30, y: 20)
        }
        .padding(.horizontal, Theme.Spacing.screenPadding)
        .padding(.vertical, 40)
    }
}
