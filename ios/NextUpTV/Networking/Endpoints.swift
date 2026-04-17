import Foundation

enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case delete = "DELETE"
}

struct Endpoint {
    let path: String
    let method: HTTPMethod
    let body: Encodable?
    let queryItems: [URLQueryItem]

    init(path: String, method: HTTPMethod = .get, body: Encodable? = nil, queryItems: [URLQueryItem] = []) {
        self.path = path
        self.method = method
        self.body = body
        self.queryItems = queryItems
    }

    var url: URL {
        var components = URLComponents(url: ServerConfig.baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !queryItems.isEmpty { components.queryItems = queryItems }
        return components.url!
    }
}

// MARK: - Auth (no bearer token needed)

extension Endpoint {
    static func deviceStart() -> Endpoint {
        Endpoint(path: "/api/v1/auth/device/start", method: .post)
    }

    static func devicePoll(deviceCode: String) -> Endpoint {
        Endpoint(path: "/api/v1/auth/device/poll", method: .post, body: ["device_code": deviceCode])
    }

    static func refreshToken(_ token: String) -> Endpoint {
        Endpoint(path: "/api/v1/auth/auth/refresh", method: .post, body: ["refresh_token": token])
    }

    static func logout(_ token: String) -> Endpoint {
        Endpoint(path: "/api/v1/auth/auth/logout", method: .post, body: ["refresh_token": token])
    }
}

// MARK: - Media

extension Endpoint {
    static func homeBundle() -> Endpoint {
        Endpoint(path: "/api/v1/media/home-bundle")
    }

    static func bestBet(mediaType: String) -> Endpoint {
        Endpoint(path: "/api/v1/media/best-bet/\(mediaType)")
    }

    static func topPicks() -> Endpoint {
        Endpoint(path: "/api/v1/media/top-picks")
    }

    static func trending(mediaType: String) -> Endpoint {
        Endpoint(path: "/api/v1/media/trending/\(mediaType)")
    }

    static func mediaDetail(mediaType: String, externalId: String) -> Endpoint {
        Endpoint(path: "/api/v1/media/\(mediaType)/\(externalId)")
    }

    static func tasteDNA() -> Endpoint {
        Endpoint(path: "/api/v1/media/taste-dna")
    }
}

// MARK: - Profile / Library

extension Endpoint {
    static func library(mediaType: String? = nil, status: String? = nil) -> Endpoint {
        var items: [URLQueryItem] = []
        if let mediaType { items.append(.init(name: "media_type", value: mediaType)) }
        if let status { items.append(.init(name: "status", value: status)) }
        return Endpoint(path: "/api/v1/profile/", queryItems: items)
    }

    static func createEntry(_ entry: CreateEntryRequest) -> Endpoint {
        Endpoint(path: "/api/v1/profile/", method: .post, body: entry)
    }

    static func updateEntry(id: Int, updates: UpdateEntryRequest) -> Endpoint {
        Endpoint(path: "/api/v1/profile/\(id)", method: .put, body: updates)
    }

    static func deleteEntry(id: Int) -> Endpoint {
        Endpoint(path: "/api/v1/profile/\(id)", method: .delete)
    }
}

// MARK: - Together

extension Endpoint {
    static func togetherUsers() -> Endpoint {
        Endpoint(path: "/api/v1/together/users")
    }

    static func compare(otherUserId: Int) -> Endpoint {
        Endpoint(path: "/api/v1/together/compare", queryItems: [.init(name: "other_user_id", value: "\(otherUserId)")])
    }
}
