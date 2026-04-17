import Foundation

enum StreamingLinks {
    struct ProviderLink {
        let name: String
        let url: URL
        let logoUrl: String?
    }

    static func links(for providers: [WatchProvider], title: String, mediaType: String, externalId: String) -> [ProviderLink] {
        let query = title.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? title
        var results: [ProviderLink] = []

        for provider in providers {
            guard let url = url(for: provider.name, title: title, query: query, mediaType: mediaType, tmdbId: externalId) else { continue }
            results.append(ProviderLink(name: provider.name, url: url, logoUrl: provider.logoUrl))
        }

        return results
    }

    private static func url(for provider: String, title: String, query: String, mediaType: String, tmdbId: String) -> URL? {
        let lowered = provider.lowercased()

        if lowered.contains("netflix") {
            return URL(string: "nflx://www.netflix.com/search?q=\(query)")
        }
        if lowered.contains("disney") {
            return URL(string: "https://www.disneyplus.com/search/\(query)")
        }
        if lowered.contains("hulu") {
            return URL(string: "hulu://search?query=\(query)")
        }
        if lowered.contains("amazon") || lowered.contains("prime") {
            return URL(string: "aiv://aiv/search?searchterm=\(query)")
        }
        if lowered.contains("hbo") || lowered.contains("max") {
            return URL(string: "hbomax://search?q=\(query)")
        }
        if lowered.contains("apple tv") || lowered.contains("apple tv+") {
            return URL(string: "https://tv.apple.com/search?term=\(query)")
        }
        if lowered.contains("paramount") {
            return URL(string: "paramountplus://search?q=\(query)")
        }
        if lowered.contains("peacock") {
            return URL(string: "peacock://search?query=\(query)")
        }
        if lowered.contains("youtube") {
            return URL(string: "youtube://results?search_query=\(query)")
        }

        return nil
    }
}
