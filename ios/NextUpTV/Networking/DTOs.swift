import Foundation

struct TokenResponse: Codable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
    }
}

struct DeviceStartResponse: Codable {
    let deviceCode: String
    let userCode: String
    let verificationUri: String
    let expiresIn: Int
    let interval: Int

    enum CodingKeys: String, CodingKey {
        case deviceCode = "device_code"
        case userCode = "user_code"
        case verificationUri = "verification_uri"
        case expiresIn = "expires_in"
        case interval
    }
}

struct ErrorResponse: Codable {
    let detail: String
}

// MARK: - Media

struct MediaItem: Codable, Identifiable, Hashable {
    let externalId: String
    let source: String?
    let mediaType: String
    let title: String
    let imageUrl: String?
    let year: Int?
    let creator: String?
    let genres: String?
    let description: String?
    let externalUrl: String?
    let backdropUrl: String?
    let reason: String?
    let watchProviders: [WatchProvider]?
    let signalScore: Double?

    var id: String { "\(source ?? "unknown"):\(externalId)" }

    enum CodingKeys: String, CodingKey {
        case externalId = "external_id"
        case source
        case mediaType = "media_type"
        case title
        case imageUrl = "image_url"
        case year, creator, genres, description
        case externalUrl = "external_url"
        case backdropUrl = "backdrop_url"
        case reason
        case watchProviders = "watch_providers"
        case signalScore = "signal_score"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        externalId = try c.decode(String.self, forKey: .externalId)
        source = try c.decodeIfPresent(String.self, forKey: .source)
        mediaType = try c.decode(String.self, forKey: .mediaType)
        title = try c.decode(String.self, forKey: .title)
        imageUrl = try c.decodeIfPresent(String.self, forKey: .imageUrl)
        year = try c.decodeIfPresent(Int.self, forKey: .year)
        creator = try c.decodeIfPresent(String.self, forKey: .creator)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        externalUrl = try c.decodeIfPresent(String.self, forKey: .externalUrl)
        backdropUrl = try c.decodeIfPresent(String.self, forKey: .backdropUrl)
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
        watchProviders = try c.decodeIfPresent([WatchProvider].self, forKey: .watchProviders)
        signalScore = try c.decodeIfPresent(Double.self, forKey: .signalScore)

        if let str = try? c.decodeIfPresent(String.self, forKey: .genres) {
            genres = str
        } else if let arr = try? c.decodeIfPresent([String].self, forKey: .genres) {
            genres = arr.joined(separator: ", ")
        } else {
            genres = nil
        }
    }
}

struct TonightPick: Codable, Hashable {
    let item: MediaItem
    let reason: String
    let providers: [String]
}

struct HomeBundle: Codable {
    let tonight: TonightPick?
    let topPicks: [MediaItem]?
    let suggestions: HomeSuggestions?
    let themes: [String: [MediaItem]]?
    let insights: [Insight]?

    enum CodingKeys: String, CodingKey {
        case tonight
        case topPicks = "top_picks"
        case suggestions, themes, insights
    }
}

struct Insight: Codable, Hashable {
    let icon: String?
    let text: String
}

struct HomeSuggestions: Codable {
    let quickPick: MediaItem?
    let deepDive: MediaItem?
    let wildcard: MediaItem?

    enum CodingKeys: String, CodingKey {
        case quickPick = "quick_pick"
        case deepDive = "deep_dive"
        case wildcard
    }
}

struct WatchProvider: Codable, Hashable {
    let name: String
    let logoUrl: String?
    let type: String?

    enum CodingKeys: String, CodingKey {
        case name
        case logoUrl = "logo_url"
        case type
    }
}

struct BestBet: Codable {
    let pick: MediaItem?
    let anchor: MediaItem?
    let reason: String?
}

// MARK: - Library

struct MediaEntry: Codable, Identifiable, Hashable {
    let id: Int
    let externalId: String
    let source: String
    let title: String
    let mediaType: String
    let imageUrl: String?
    let year: Int?
    let creator: String?
    let genres: String?
    let description: String?
    let status: String
    let rating: Double?
    let notes: String?
    let tags: String?

    enum CodingKeys: String, CodingKey {
        case id
        case externalId = "external_id"
        case source
        case title
        case mediaType = "media_type"
        case imageUrl = "image_url"
        case year, creator, genres, description
        case status, rating, notes, tags
    }
}

struct CreateEntryRequest: Codable {
    let externalId: String
    let source: String
    let title: String
    let mediaType: String
    let imageUrl: String?
    let year: Int?
    let creator: String?
    let genres: String?
    let description: String?
    let status: String
    let rating: Double?

    enum CodingKeys: String, CodingKey {
        case externalId = "external_id"
        case source
        case title
        case mediaType = "media_type"
        case imageUrl = "image_url"
        case year, creator, genres, description
        case status, rating
    }
}

struct UpdateEntryRequest: Codable {
    let status: String?
    let rating: Double?
    let notes: String?
}

// MARK: - Together

struct TogetherUser: Codable, Identifiable {
    let id: Int
    let name: String
    let picture: String?
}

struct SharedLovedItem: Codable, Hashable {
    let title: String
    let mediaType: String
    let imageUrl: String?
    let myRating: Double?
    let theirRating: Double?

    enum CodingKeys: String, CodingKey {
        case title
        case mediaType = "media_type"
        case imageUrl = "image_url"
        case myRating = "my_rating"
        case theirRating = "their_rating"
    }
}

struct CompareResult: Codable {
    let otherUser: TogetherUser?
    let myName: String?
    let sharedLoved: [SharedLovedItem]?
    let sharedGenres: [String]?
    let watchTogether: MediaItem?
    let candidates: [MediaItem]?

    enum CodingKeys: String, CodingKey {
        case otherUser = "other_user"
        case myName = "my_name"
        case sharedLoved = "shared_loved"
        case sharedGenres = "shared_genres"
        case watchTogether = "watch_together"
        case candidates
    }
}
