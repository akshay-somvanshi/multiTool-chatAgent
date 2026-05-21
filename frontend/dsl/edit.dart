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

// WorkingShimmerText widget — shimmer text that streams the live agent status
// from Firestore instead of showing a static "Working..." string.
// Firestore path: messages/{userId}/sessions/{YYYYMMDD}  field: status
// The userId is passed in from FlutterFlow as `currentUserUid`.
// Falls back to widget.text ("Working...") until the first Firestore snapshot arrives.
const _workingShimmerTextCode = r'''
import 'package:cloud_firestore/cloud_firestore.dart';

class WorkingShimmerText extends StatefulWidget {
  const WorkingShimmerText({
    super.key,
    this.width,
    this.height,
    this.text,
    this.fontSize,
    this.userId,
  });

  final double? width;
  final double? height;
  final String? text;
  final double? fontSize;
  final String? userId;

  @override
  State<WorkingShimmerText> createState() => _WorkingShimmerTextState();
}

class _WorkingShimmerTextState extends State<WorkingShimmerText>
    with TickerProviderStateMixin {
  late AnimationController _controller;

  /// Session ID matches the backend: YYYYMMDD in local time.
  String get _sessionId {
    final now = DateTime.now();
    final mm = now.month.toString().padLeft(2, '0');
    final dd = now.day.toString().padLeft(2, '0');
    return '${now.year}$mm$dd';
  }

  Stream<DocumentSnapshot<Map<String, dynamic>>>? get _statusStream {
    final uid = widget.userId;
    if (uid == null || uid.isEmpty) return null;
    return FirebaseFirestore.instance
        .collection('messages')
        .doc(uid)
        .collection('sessions')
        .doc(_sessionId)
        .snapshots();
  }

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Widget _shimmer(String text) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return ShaderMask(
          shaderCallback: (bounds) {
            return LinearGradient(
              begin: Alignment(-1.0 + (_controller.value * 2), 0),
              end: const Alignment(1.0, 0),
              colors: const [
                Color(0xFF9AA0A6),
                Color(0xFFE5E7EB),
                Color(0xFF9AA0A6),
              ],
            ).createShader(bounds);
          },
          child: child,
        );
      },
      child: Text(
        text,
        style: TextStyle(
          fontSize: widget.fontSize ?? 18.0,
          fontWeight: FontWeight.w600,
          color: const Color(0xFF9AA0A6),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final fallback = widget.text ?? 'Working...';
    final stream = _statusStream;

    if (stream == null) return _shimmer(fallback);

    return StreamBuilder<DocumentSnapshot<Map<String, dynamic>>>(
      stream: stream,
      builder: (context, snapshot) {
        String status = fallback;
        if (snapshot.hasData && snapshot.data!.exists) {
          final data = snapshot.data!.data();
          final raw = data?['status'];
          if (raw is String && raw.isNotEmpty) status = raw;
        }
        return _shimmer(status);
      },
    );
  }
}
''';

// MarkdownMessage widget — renders agent message text with markdown formatting.
// flutter_markdown is already a project dependency (^0.7.4); no new pub dep needed.
// MarkdownBody is intrinsically sized (no fixed height) so it flows naturally in
// a Column beside the HtmlViewer component below it.
const _markdownMessageCode = r'''
import 'package:flutter_markdown/flutter_markdown.dart';

class MarkdownMessage extends StatelessWidget {
  const MarkdownMessage({
    super.key,
    this.width,
    this.height, // accepted by FlutterFlow but unused — MarkdownBody auto-sizes vertically
    required this.message,
  });

  final double? width;
  final double? height;
  final String message;

  @override
  Widget build(BuildContext context) {
    // null/infinite width → fill available horizontal space.
    final effectiveWidth =
        (width != null && width!.isFinite) ? width! : null;

    final bodyStyle = FlutterFlowTheme.of(context).bodyMedium;

    return SizedBox(
      width: effectiveWidth,
      child: MarkdownBody(
        data: message,
        selectable: true,
        softLineBreak: true,
        styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
          p: bodyStyle,
          strong: bodyStyle.copyWith(fontWeight: FontWeight.bold),
          em: bodyStyle.copyWith(fontStyle: FontStyle.italic),
          listBullet: bodyStyle,
          blockquote: bodyStyle.copyWith(
            color: bodyStyle.color?.withOpacity(0.7),
          ),
          code: bodyStyle.copyWith(
            fontFamily: 'monospace',
            fontSize:
                bodyStyle.fontSize != null ? bodyStyle.fontSize! - 1 : 13.0,
          ),
          codeblockDecoration: BoxDecoration(
            color: FlutterFlowTheme.of(context).primaryBackground,
            borderRadius: BorderRadius.circular(8.0),
          ),
        ),
      ),
    );
  }
}
''';

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

    return SizedBox(
      width: effectiveWidth,
      height: effectiveHeight,
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(4.0),
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
    // flutter_markdown is already in pubspec.yaml (^0.7.4) — no extra dep needed.
  });

  // 2. Add or update the unified HtmlViewer widget.
  app.raw((project) {
    try {
      updateCustomWidget(
        project,
        name: 'HtmlViewer',
        code: _htmlViewerCode,
        description: 'Renders agent HTML content natively via flutter_html (no WebView)',
      );
    } catch (_) {
      addCustomWidget(
        project,
        name: 'HtmlViewer',
        code: _htmlViewerCode,
        description: 'Renders agent HTML content natively via flutter_html (no WebView)',
      );
    }
  });

  // 3. Update WorkingShimmerText to stream live agent status from Firestore.
  app.raw((project) {
    try {
      updateCustomWidget(
        project,
        name: 'WorkingShimmerText',
        code: _workingShimmerTextCode,
        description: 'Shimmer text that streams the live agent status from Firestore',
      );
    } catch (_) {
      addCustomWidget(
        project,
        name: 'WorkingShimmerText',
        code: _workingShimmerTextCode,
        description: 'Shimmer text that streams the live agent status from Firestore',
      );
    }
  });

  // 4. Add or update the MarkdownMessage widget.
  //    Replace the plain Text widget on Home_Page (AI message bubble) with this
  //    widget so that **bold**, *italic*, lists, and code blocks render properly.
  app.raw((project) {
    try {
      updateCustomWidget(
        project,
        name: 'MarkdownMessage',
        code: _markdownMessageCode,
        description: 'Renders AI message text with markdown formatting (bold, italic, lists, code)',
      );
    } catch (_) {
      addCustomWidget(
        project,
        name: 'MarkdownMessage',
        code: _markdownMessageCode,
        description: 'Renders AI message text with markdown formatting (bold, italic, lists, code)',
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
