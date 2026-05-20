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
// Uses flutter_html (already a project dependency) instead of webview_flutter.
// On Flutter Web, webview_flutter renders via an <iframe> platform view which
// causes surrounding Flutter-canvas widgets (like the AI message text above it
// in the chat list) to go blank due to compositing-layer conflicts. flutter_html
// renders HTML natively inside Flutter — no platform view, no blank-out.
//
// flutter_html 3.x splits table support into a separate package (flutter_html_table).
// TableHtmlExtension must be passed explicitly — without it <table> renders blank.
// Explicit text colors are required because flutter_html inherits the app theme's
// default text color, which can be invisible against secondaryBackground (white).
const _htmlViewerCode = r'''
import 'package:flutter_html/flutter_html.dart';
import 'package:flutter_html_table/flutter_html_table.dart';

class HtmlViewer extends StatelessWidget {
  const HtmlViewer({
    super.key,
    this.width,
    this.height,
    required this.content,
  });

  final double? width;
  final double? height;
  final String content;

  @override
  Widget build(BuildContext context) {
    // Guard against infinity/very-large values FlutterFlow can pass when the
    // widget is placed in an "expand" layout.
    final effectiveHeight =
        (height != null && height!.isFinite && height! <= 600)
            ? height!
            : 320.0;
    // null width = fill available horizontal space; infinity = unconstrained.
    final effectiveWidth =
        (width != null && width!.isFinite) ? width! : null;

    // JSON path extractors can deliver escaped \n sequences instead of real newlines.
    final normalized = content.replaceAll(r'\n', '\n');

    return Container(
      width: effectiveWidth,
      height: effectiveHeight,
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
          padding: const EdgeInsets.all(12.0),
          child: Html(
            data: normalized,
            // Required in flutter_html 3.x — table tags are not built-in.
            extensions: const [TableHtmlExtension()],
            style: {
              // Explicit body/inline text color prevents invisible-text when the
              // app theme's default text color matches secondaryBackground.
              'body': Style(
                color: const Color(0xFF1A1A2E),
                fontSize: FontSize(14.0),
              ),
              'p': Style(
                color: const Color(0xFF1A1A2E),
                lineHeight: LineHeight(1.5),
                margin: Margins.only(bottom: 8),
              ),
              'span': Style(color: const Color(0xFF1A1A2E)),
              'li': Style(color: const Color(0xFF1A1A2E)),
              'th': Style(
                backgroundColor: const Color(0xFFE8F5E9),
                color: const Color(0xFF2E7D32),
                fontWeight: FontWeight.w600,
                padding: HtmlPaddings.symmetric(horizontal: 12, vertical: 10),
              ),
              'td': Style(
                color: const Color(0xFF37474F),
                padding: HtmlPaddings.symmetric(horizontal: 12, vertical: 8),
              ),
              'h1': Style(color: const Color(0xFF1B5E20), fontSize: FontSize(20.0)),
              'h2': Style(color: const Color(0xFF1B5E20), fontSize: FontSize(18.0)),
              'h3': Style(color: const Color(0xFF1B5E20), fontSize: FontSize(16.0)),
            },
          ),
        ),
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
    if (findPubDependency(project, name: 'webview_flutter') == null) {
      addPubDependency(project, name: 'webview_flutter', version: '^4.7.0');
    }
    // flutter_html 3.x: table support is opt-in via a companion package.
    if (findPubDependency(project, name: 'flutter_html_table') == null) {
      addPubDependency(project, name: 'flutter_html_table', version: '^3.0.0');
    }
  });

  // 2. Add or update the unified HtmlViewer widget.
  //    MarkdownTableViewer and MermaidViewer are left in place because existing
  //    page layouts still reference them. Once the FlutterFlow conditional is
  //    updated to point to HtmlViewer, those old widgets can be removed manually.
  app.raw((project) {
    try {
      // Succeeds on re-runs once the widget exists in the project.
      updateCustomWidget(
        project,
        name: 'HtmlViewer',
        code: _htmlViewerCode,
        description: 'Renders agent HTML content in a WebView with a consistent base stylesheet',
      );
    } catch (_) {
      // First run: widget does not exist yet.
      addCustomWidget(
        project,
        name: 'HtmlViewer',
        code: _htmlViewerCode,
        description: 'Renders agent HTML content in a WebView with a consistent base stylesheet',
      );
    }
  });
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
