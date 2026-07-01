export type WorkspaceCancellationPorts = {
  cancelChat: () => void;
  cancelGroup: () => void;
  cancelNews: () => void;
  cancelWebLookup: () => void;
  invalidateTool: () => void;
};

export type WorkspaceArtifactPorts = {
  clearRag: () => void;
  clearToolRun: () => void;
  clearWorkflow: () => void;
};

export class WorkspaceCoordinator {
  constructor(
    private readonly cancellation: WorkspaceCancellationPorts,
    private readonly artifacts: WorkspaceArtifactPorts
  ) {}

  cancelAllActiveOperations() {
    this.cancellation.cancelChat();
    this.cancellation.cancelGroup();
    this.cancellation.cancelNews();
    this.cancellation.cancelWebLookup();
    this.cancellation.invalidateTool();
  }

  clearChatArtifacts() {
    this.artifacts.clearRag();
    this.artifacts.clearToolRun();
    this.artifacts.clearWorkflow();
  }
}
