import SwiftUI

struct PosterCard: View {
    let item: MediaItem
    var width: CGFloat = 200
    var showTitle: Bool = true

    private var height: CGFloat { width * 1.5 }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AsyncImage(url: URL(string: item.imageUrl ?? "")) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                case .failure:
                    placeholder
                default:
                    placeholder
                        .overlay(ProgressView())
                }
            }
            .frame(width: width, height: height)
            .clipShape(RoundedRectangle(cornerRadius: 10))

            if showTitle {
                Text(item.title)
                    .font(.caption)
                    .lineLimit(2)
                    .frame(width: width, alignment: .leading)
            }

            if let reason = item.reason {
                Text(reason)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .frame(width: width, alignment: .leading)
            }
        }
    }

    private var placeholder: some View {
        RoundedRectangle(cornerRadius: 10)
            .fill(.quaternary)
            .frame(width: width, height: height)
            .overlay {
                VStack(spacing: 4) {
                    Image(systemName: mediaIcon)
                        .font(.title)
                        .foregroundStyle(.tertiary)
                    Text(item.title)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 8)
                }
            }
    }

    private var mediaIcon: String {
        switch item.mediaType {
        case "movie": return "film"
        case "tv": return "tv"
        case "book": return "book"
        case "podcast": return "headphones"
        default: return "questionmark"
        }
    }
}
