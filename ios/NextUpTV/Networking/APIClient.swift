import Foundation
import SwiftUI

@MainActor
final class APIClient: ObservableObject {
    private let session = URLSession.shared
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()
    private let decoder = JSONDecoder()
    private let authStore: AuthStore

    init(authStore: AuthStore) {
        self.authStore = authStore
    }

    // MARK: - Public

    func request<T: Decodable>(_ endpoint: Endpoint) async throws -> T {
        let data = try await execute(endpoint, attemptRefresh: true)
        return try decoder.decode(T.self, from: data)
    }

    func requestVoid(_ endpoint: Endpoint) async throws {
        _ = try await execute(endpoint, attemptRefresh: true)
    }

    // MARK: - Auth (no bearer needed)

    func unauthenticatedRequest<T: Decodable>(_ endpoint: Endpoint) async throws -> T {
        let data = try await perform(buildRequest(for: endpoint))
        return try decoder.decode(T.self, from: data)
    }

    // MARK: - Internal

    private func execute(_ endpoint: Endpoint, attemptRefresh: Bool) async throws -> Data {
        var req = buildRequest(for: endpoint)

        if let token = authStore.accessToken {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        do {
            return try await perform(req)
        } catch APIError.unauthorized where attemptRefresh {
            try await authStore.refreshTokens()
            return try await execute(endpoint, attemptRefresh: false)
        }
    }

    private func buildRequest(for endpoint: Endpoint) -> URLRequest {
        var req = URLRequest(url: endpoint.url)
        req.httpMethod = endpoint.method.rawValue
        req.setValue("application/json", forHTTPHeaderField: "Accept")

        if let body = endpoint.body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            if let dict = body as? [String: String] {
                req.httpBody = try? JSONSerialization.data(withJSONObject: dict)
            } else {
                req.httpBody = try? encoder.encode(AnyEncodable(body))
            }
        }

        return req
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.unknown
        }
        switch http.statusCode {
        case 200..<300:
            return data
        case 401:
            throw APIError.unauthorized
        case 400:
            if let err = try? decoder.decode(ErrorResponse.self, from: data) {
                throw APIError.badRequest(err.detail)
            }
            throw APIError.httpError(http.statusCode)
        default:
            throw APIError.httpError(http.statusCode)
        }
    }
}

enum APIError: Error, LocalizedError {
    case unauthorized
    case badRequest(String)
    case httpError(Int)
    case unknown

    var errorDescription: String? {
        switch self {
        case .unauthorized: return "Session expired"
        case .badRequest(let msg): return msg
        case .httpError(let code): return "Server error (\(code))"
        case .unknown: return "Something went wrong"
        }
    }
}

private struct AnyEncodable: Encodable {
    let value: Encodable
    init(_ value: Encodable) { self.value = value }
    func encode(to encoder: Encoder) throws { try value.encode(to: encoder) }
}
