import SwiftUI

struct PosterCard: View {
    let item: MediaItem
    var width: CGFloat = 220
    var showTitle: Bool = true
    var showSignal: Bool = true

    private var height: CGFloat { width * 1.5 }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            posterImage

            if showTitle {
                Text(item.title)
                    .font(.system(size: 22, weight: .medium))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                    .frame(width: width, alignment: .leading)
            }

            if let reason = item.reason, !reason.isEmpty {
                Text(reason)
                    .font(.system(size: 18))
                    .foregroundStyle(Theme.inkDim)
                    .lineLimit(2)
                    .frame(width: width, alignment: .leading)
            }
        }
    }

    private var posterImage: some View {
        ZStack(alignment: .topLeading) {
            AsyncImage(url: URL(string: item.imageUrl ?? "")) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().aspectRatio(contentMode: .fill)
                case .failure:
                    placeholder
                default:
                    placeholder.overlay(ProgressView().tint(Theme.inkFaint))
                }
            }
            .frame(width: width, height: height)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(Theme.line, lineWidth: 1)
            )

            if showSignal, let signal = item.signalScore {
                SignalBadge(value: signal, size: .small)
                    .padding(10)
            }
        }
    }

    private var placeholder: some View {
        RoundedRectangle(cornerRadius: 10)
            .fill(Theme.surface2)
            .frame(width: width, height: height)
            .overlay {
                VStack(spacing: 6) {
                    Image(systemName: mediaIcon)
                        .font(.title)
                        .foregroundStyle(Theme.inkFaint)
                    Text(item.title)
                        .font(.caption2)
                        .foregroundStyle(Theme.inkFaint)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 8)
                }
            }
    }

    private var mediaIcon: String {
        switch item.mediaType {
        case "movie":   return "film"
        case "tv":      return "tv"
        case "book":    return "book"
        case "podcast": return "headphones"
        default:        return "questionmark"
        }
    }
}
