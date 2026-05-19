library;

import 'dart:io';

import 'package:flutterflow_ai/flutterflow_ai.dart';

Future<void> main(List<String> args) async {
  final options = _parseCliOptions(args);
  try {
    await flutterFlowAI(
      buildEditFlow,
      apiKey: options.apiKey,
      baseUrl: options.baseUrl,
      projectName: options.projectName,
      projectId: options.projectId,
      findOrCreate: options.findOrCreate,
      allowNewProject: options.allowNewProject,
      dryRun: options.dryRun,
      commitMessage: options.commitMessage,
    );
  } catch (error) {
    stderr.writeln('Error: ${formatFlutterFlowAIError(error)}');
    exit(1);
  }
}

// ---------------------------------------------------------------------------
// Widget code strings
// Note: FF boilerplate imports are auto-prepended; code starts after the
// "// Begin custom widget code" marker.
// HTML strings avoid triple-quotes via concatenation to prevent premature
// string termination inside the r''' DSL string.
// ---------------------------------------------------------------------------

// ignore_for_file: prefer_adjacent_string_concatenation
const _markdownTableViewerCode = r'''
import 'package:flutter_markdown/flutter_markdown.dart';

class MarkdownTableViewer extends StatefulWidget {
  const MarkdownTableViewer({
    super.key,
    this.width,
    this.height,
    required this.content,
  });

  final double? width;
  final double? height;
  final String content;

  @override
  State<MarkdownTableViewer> createState() => _MarkdownTableViewerState();
}

class _MarkdownTableViewerState extends State<MarkdownTableViewer> {
  @override
  Widget build(BuildContext context) {
    return Container(
      width: widget.width,
      decoration: BoxDecoration(
        color: FlutterFlowTheme.of(context).secondaryBackground,
        borderRadius: BorderRadius.circular(12.0),
        border: Border.all(
          color: FlutterFlowTheme.of(context).alternate,
          width: 1.0,
        ),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12.0),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.all(4.0),
          child: ConstrainedBox(
            constraints: BoxConstraints(minWidth: widget.width ?? 0),
            child: MarkdownBody(
              data: widget.content,
              styleSheet:
                  MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
                tableHead:
                    FlutterFlowTheme.of(context).bodyMedium.copyWith(
                  fontWeight: FontWeight.bold,
                  color: FlutterFlowTheme.of(context).primaryText,
                ),
                tableBody:
                    FlutterFlowTheme.of(context).bodySmall.copyWith(
                  color: FlutterFlowTheme.of(context).primaryText,
                ),
                tableBorder: TableBorder.all(
                  color: FlutterFlowTheme.of(context).alternate,
                  width: 1.0,
                ),
                tableColumnWidth: const FlexColumnWidth(),
                tableCellsPadding: const EdgeInsets.symmetric(
                  horizontal: 12.0,
                  vertical: 8.0,
                ),
                p: FlutterFlowTheme.of(context).bodyMedium.copyWith(
                  color: FlutterFlowTheme.of(context).primaryText,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
''';

// HTML uses string concatenation to avoid triple-quote conflicts
const _mermaidViewerCode = r'''
import 'package:webview_flutter/webview_flutter.dart';

class MermaidViewer extends StatefulWidget {
  const MermaidViewer({
    super.key,
    this.width,
    this.height,
    required this.content,
  });

  final double? width;
  final double? height;
  final String content;

  @override
  State<MermaidViewer> createState() => _MermaidViewerState();
}

class _MermaidViewerState extends State<MermaidViewer> {
  late final WebViewController _controller;

  String _buildHtml(String mermaidContent) {
    final escaped = mermaidContent.replaceAll("'", r"\'");
    return '<!DOCTYPE html><html><head>' +
        '<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">' +
        '<style>' +
        'body{margin:0;padding:16px;background:transparent;font-family:sans-serif;}' +
        '.mermaid{display:flex;justify-content:center;}' +
        'svg{max-width:100%;height:auto;}' +
        '</style></head><body>' +
        '<div class="mermaid">' + escaped + '</div>' +
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>' +
        '<script>mermaid.initialize({startOnLoad:true,theme:"neutral",securityLevel:"loose"});</script>' +
        '</body></html>';
  }

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.transparent)
      ..loadHtmlString(_buildHtml(widget.content));
  }

  @override
  void didUpdateWidget(covariant MermaidViewer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.content != widget.content) {
      _controller.loadHtmlString(_buildHtml(widget.content));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: widget.width,
      height: widget.height ?? 280.0,
      decoration: BoxDecoration(
        color: FlutterFlowTheme.of(context).secondaryBackground,
        borderRadius: BorderRadius.circular(12.0),
        border: Border.all(
          color: FlutterFlowTheme.of(context).alternate,
          width: 1.0,
        ),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12.0),
        child: WebViewWidget(controller: _controller),
      ),
    );
  }
}
''';

// ---------------------------------------------------------------------------
// Edit flow
// ---------------------------------------------------------------------------
void buildEditFlow(App app) {
  // 1. Pub dependencies — guarded against duplicate errors on rerun
  app.raw((project) {
    if (findPubDependency(project, name: 'flutter_markdown') == null) {
      addPubDependency(project, name: 'flutter_markdown', version: '^0.7.4');
    }
    if (findPubDependency(project, name: 'webview_flutter') == null) {
      addPubDependency(project, name: 'webview_flutter', version: '^4.7.0');
    }
  });

  // 2. Custom widgets — app.customWidget uses ensureCustomWidget internally
  //    (no-ops on identical rerun, throws on mismatched payload)
  app.customWidget(
    'MarkdownTableViewer',
    parameters: {'content': string},
    description: 'Renders a markdown-formatted table from the agent ui_component response',
    code: _markdownTableViewerCode,
  );

  app.customWidget(
    'MermaidViewer',
    parameters: {'content': string, 'diagramHeight': double_.withDefault(280.0)},
    description: 'Renders a Mermaid.js process map or flowchart in a WebView',
    code: _mermaidViewerCode,
  );
}

// ---------------------------------------------------------------------------
// CLI boilerplate
// ---------------------------------------------------------------------------
final class _CliOptions {
  const _CliOptions({
    this.apiKey,
    this.baseUrl,
    this.projectName,
    this.projectId,
    this.findOrCreate = false,
    this.allowNewProject = false,
    this.dryRun = false,
    this.commitMessage,
  });

  final String? apiKey;
  final String? baseUrl;
  final String? projectName;
  final String? projectId;
  final bool findOrCreate;
  final bool allowNewProject;
  final bool dryRun;
  final String? commitMessage;
}

_CliOptions _parseCliOptions(List<String> args) {
  String? apiKey;
  String? baseUrl;
  String? projectName;
  String? projectId;
  String? commitMessage;
  var findOrCreate = false;
  var allowNewProject = false;
  var dryRun = false;

  for (var i = 0; i < args.length; i++) {
    final arg = args[i];
    switch (arg) {
      case '--help':
      case '-h':
        _printUsage();
        exit(0);
      case '--api-key':
        apiKey = _requireValue(args, ++i, '--api-key');
      case '--base-url':
        baseUrl = _requireValue(args, ++i, '--base-url');
      case '--project-name':
        projectName = _requireValue(args, ++i, '--project-name');
      case '--project-id':
        projectId = _requireValue(args, ++i, '--project-id');
      case '--commit-message':
        commitMessage = _requireValue(args, ++i, '--commit-message');
      case '--find-or-create':
        findOrCreate = true;
      case '--allow-new-project':
        allowNewProject = true;
      case '--dry-run':
        dryRun = true;
      default:
        stderr.writeln('Unknown option: $arg');
        _printUsage();
        exit(64);
    }
  }

  return _CliOptions(
    apiKey: apiKey,
    baseUrl: baseUrl,
    projectName: projectName,
    projectId: projectId,
    findOrCreate: findOrCreate,
    allowNewProject: allowNewProject,
    dryRun: dryRun,
    commitMessage: commitMessage,
  );
}

String _requireValue(List<String> args, int index, String flag) {
  if (index >= args.length) {
    stderr.writeln('Missing value for $flag.');
    _printUsage();
    exit(64);
  }
  return args[index];
}

void _printUsage() {
  stdout.writeln('''
Add MarkdownTableViewer + MermaidViewer widgets to the Dash project.

Usage:
  dart run dsl/edit.dart [options]

Options:
  --api-key <key>           FlutterFlow API key (or set FF_API_KEY env var).
  --project-id <id>         Target project ID.
  --commit-message <text>   Commit message for the push.
  --dry-run                 Compile and validate without pushing.
  --help, -h                Show this help.
''');
}
