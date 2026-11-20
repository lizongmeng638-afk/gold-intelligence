import AppKit
import WebKit

// Native Mac shell. The analysis stays on the user's existing Streamlit site.
// The bundled history is a dated, read-only snapshot for offline reading.
final class GoldApplication: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    let site = URL(string: "https://gold-intelligence-lzm.streamlit.app/")!
    var window: NSWindow!
    var web: WKWebView!
    var status = NSTextField(labelWithString: "")
    var downloads: [ObjectIdentifier: WKDownload] = [:]
    var offline = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "GOLD INTELLIGENCE · 黄金智能分析中心"
        window.minSize = NSSize(width: 760, height: 600)
        window.isReleasedWhenClosed = false
        let root = NSStackView()
        root.orientation = .vertical
        root.spacing = 0
        let toolbar = NSStackView()
        toolbar.orientation = .horizontal
        toolbar.spacing = 12
        toolbar.edgeInsets = NSEdgeInsets(top: 10, left: 16, bottom: 10, right: 16)
        let live = NSButton(title: "在线分析中心", target: self, action: #selector(openLive))
        let saved = NSButton(title: "离线历史资料", target: self, action: #selector(openOffline))
        let reload = NSButton(title: "刷新", target: self, action: #selector(refresh))
        let browser = NSButton(title: "在浏览器打开", target: self, action: #selector(openBrowser))
        for button in [live, saved, reload, browser] { button.bezelStyle = .rounded; toolbar.addArrangedSubview(button) }
        status.font = .systemFont(ofSize: 11)
        status.textColor = .secondaryLabelColor
        status.lineBreakMode = .byTruncatingMiddle
        toolbar.addArrangedSubview(status)
        root.addArrangedSubview(toolbar)
        root.addArrangedSubview(web)
        window.contentView = root
        web.translatesAutoresizingMaskIntoConstraints = false
        toolbar.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            toolbar.widthAnchor.constraint(equalTo: root.widthAnchor),
            web.widthAnchor.constraint(equalTo: root.widthAnchor),
            web.heightAnchor.constraint(greaterThanOrEqualToConstant: 400)
        ])
        buildMenus()
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if ProcessInfo.processInfo.arguments.contains("--offline") { openOffline() } else { openLive() }
    }

    func buildMenus() {
        let bar = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于 GOLD INTELLIGENCE", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出 GOLD INTELLIGENCE", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        bar.addItem(appItem)
        let viewItem = NSMenuItem()
        let viewMenu = NSMenu(title: "查看")
        for (title, action, key) in [("在线分析中心", #selector(openLive), "1"), ("离线历史资料", #selector(openOffline), "2"), ("刷新", #selector(refresh), "r"), ("在浏览器打开", #selector(openBrowser), "b")] {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.target = self
            viewMenu.addItem(item)
        }
        viewItem.submenu = viewMenu
        bar.addItem(viewItem)
        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("复制", #selector(NSText.copy(_:)), "c"), ("粘贴", #selector(NSText.paste(_:)), "v"), ("全选", #selector(NSText.selectAll(_:)), "a")] {
            editMenu.addItem(withTitle: title, action: action, keyEquivalent: key)
        }
        editItem.submenu = editMenu
        bar.addItem(editItem)
        NSApp.mainMenu = bar
    }

    @objc func openLive() {
        offline = false
        status.stringValue = "正在连接 Streamlit 云端…"
        web.load(URLRequest(url: site, cachePolicy: .useProtocolCachePolicy, timeoutInterval: 25))
    }

    @objc func openOffline() {
        guard let resource = Bundle.main.resourceURL else { return }
        let url = resource.appendingPathComponent("offline/index.html")
        offline = true
        status.stringValue = "离线历史快照 · 非实时行情"
        web.loadFileURL(url, allowingReadAccessTo: resource.appendingPathComponent("offline"))
    }

    @objc func refresh() { if offline { openOffline() } else { openLive() } }
    @objc func openBrowser() { NSWorkspace.shared.open(site) }
    @objc func about() {
        let alert = NSAlert()
        alert.messageText = "GOLD INTELLIGENCE V1.3"
        alert.informativeText = "黄金智能分析中心 Mac 桌面版。在线功能使用现有 Streamlit 网站，无需 Python。离线资料为随包历史快照，不能当作最新行情。\n\n本应用未进行 Apple 公证。"
        alert.runModal()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        return true
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if !offline { status.stringValue = "在线 · gold-intelligence-lzm.streamlit.app" }
    }
    func failed(_ error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        status.stringValue = "连接失败，可点“离线历史资料”或“在浏览器打开”"
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { decisionHandler(.download); return }
        if action.navigationType == .linkActivated, let url = action.request.url, ["http", "https"].contains(url.scheme ?? ""), url.host != site.host {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url {
            if ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            else { webView.load(action.request) }
        }
        return nil
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { retainDownload(download) }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { retainDownload(download) }
    func retainDownload(_ download: WKDownload) { downloads[ObjectIdentifier(download)] = download; download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.url : nil) }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.removeValue(forKey: ObjectIdentifier(download)) }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeValue(forKey: ObjectIdentifier(download))
        status.stringValue = "下载未完成，可用“在浏览器打开”重新下载。"
    }
}

let application = NSApplication.shared
let delegate = GoldApplication()
application.delegate = delegate
application.run()
