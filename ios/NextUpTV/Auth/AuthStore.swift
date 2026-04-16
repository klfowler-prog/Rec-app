import Foundation
import SwiftUI

enum AuthState {
    case unknown
    case unauthenticated
    case authenticated
}

@MainActor
final class AuthStore: ObservableObject {
    @Published var state: AuthState = .unknown
    @Published private(set) var accessToken: String?
    private var refreshTokenValue: String?

    private let decoder = JSONDecoder()

    init() {
        if let access = KeychainStore.load(key: "access_token"),
           let refresh = KeychainStore.load(key: "refresh_token") {
            self.accessToken = access
            self.refreshTokenValue = refresh
            self.state = .authenticated
        } else {
            self.state = .unauthenticated
        }
    }

    func setTokens(_ response: TokenResponse) {
        accessToken = response.accessToken
        refreshTokenValue = response.refreshToken
        KeychainStore.save(key: "access_token", value: response.accessToken)
        KeychainStore.save(key: "refresh_token", value: response.refreshToken)
        state = .authenticated
    }

    func refreshTokens() async throws {
        guard let refresh = refreshTokenValue else {
            signOut()
            throw APIError.unauthorized
        }

        let endpoint = Endpoint.refreshToken(refresh)
        var req = URLRequest(url: endpoint.url)
        req.httpMethod = endpoint.method.rawValue
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["refresh_token": refresh])

        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            signOut()
            throw APIError.unauthorized
        }

        let tokens = try decoder.decode(TokenResponse.self, from: data)
        setTokens(tokens)
    }

    func signOut() {
        if let refresh = refreshTokenValue {
            Task {
                let endpoint = Endpoint.logout(refresh)
                var req = URLRequest(url: endpoint.url)
                req.httpMethod = endpoint.method.rawValue
                req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                req.httpBody = try? JSONSerialization.data(withJSONObject: ["refresh_token": refresh])
                _ = try? await URLSession.shared.data(for: req)
            }
        }
        accessToken = nil
        refreshTokenValue = nil
        KeychainStore.clear()
        state = .unauthenticated
    }
}
