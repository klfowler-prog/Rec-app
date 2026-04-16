import SwiftUI

struct DevicePairingView: View {
    @EnvironmentObject var authStore: AuthStore
    @State private var userCode: String?
    @State private var verificationUri: String?
    @State private var deviceCode: String?
    @State private var isPolling = false
    @State private var error: String?
    @State private var pollInterval: Int = 5

    private let decoder = JSONDecoder()

    var body: some View {
        VStack(spacing: 40) {
            Spacer()

            Image(systemName: "tv")
                .font(.system(size: 80))
                .foregroundStyle(.secondary)

            Text("Link your Apple TV")
                .font(.title)
                .bold()

            if let userCode {
                VStack(spacing: 16) {
                    Text("Go to this URL on your phone:")
                        .foregroundStyle(.secondary)

                    if let verificationUri {
                        Text(verificationUri)
                            .font(.title3)
                            .monospaced()
                            .foregroundStyle(.blue)
                    }

                    Text("and enter this code:")
                        .foregroundStyle(.secondary)

                    Text(userCode)
                        .font(.system(size: 64, weight: .bold, design: .monospaced))
                        .tracking(12)
                        .padding()

                    if isPolling {
                        ProgressView("Waiting for approval...")
                    }
                }
            } else if let error {
                VStack(spacing: 16) {
                    Text(error)
                        .foregroundStyle(.red)
                    Button("Try Again") { Task { await startPairing() } }
                }
            } else {
                ProgressView()
            }

            Spacer()
        }
        .padding(60)
        .task { await startPairing() }
    }

    private func startPairing() async {
        error = nil
        let endpoint = Endpoint.deviceStart()
        var req = URLRequest(url: endpoint.url)
        req.httpMethod = endpoint.method.rawValue

        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            let response = try decoder.decode(DeviceStartResponse.self, from: data)
            userCode = response.userCode
            verificationUri = response.verificationUri
            deviceCode = response.deviceCode
            pollInterval = response.interval
            await pollForApproval(deviceCode: response.deviceCode, expiresIn: response.expiresIn)
        } catch {
            print("DevicePairing error: \(error)")
            self.error = "Couldn't reach the server: \(error.localizedDescription)"
        }
    }

    private func pollForApproval(deviceCode: String, expiresIn: Int) async {
        isPolling = true
        let deadline = Date().addingTimeInterval(TimeInterval(expiresIn))

        while Date() < deadline && isPolling {
            try? await Task.sleep(for: .seconds(pollInterval))

            let endpoint = Endpoint.devicePoll(deviceCode: deviceCode)
            var req = URLRequest(url: endpoint.url)
            req.httpMethod = endpoint.method.rawValue
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.setValue("application/json", forHTTPHeaderField: "Accept")
            req.httpBody = try? JSONSerialization.data(withJSONObject: ["device_code": deviceCode])

            guard let (data, response) = try? await URLSession.shared.data(for: req),
                  let http = response as? HTTPURLResponse else { continue }

            if http.statusCode == 200 {
                if let tokens = try? decoder.decode(TokenResponse.self, from: data) {
                    authStore.setTokens(tokens)
                    isPolling = false
                    return
                }
            }

            if http.statusCode == 400 {
                if let err = try? decoder.decode(ErrorResponse.self, from: data) {
                    switch err.detail {
                    case "authorization_pending":
                        continue
                    case "slow_down":
                        pollInterval += 1
                        continue
                    case "expired_token":
                        break
                    default:
                        break
                    }
                }
            }
        }

        isPolling = false
        error = "Pairing timed out. Please try again."
        userCode = nil
    }
}
