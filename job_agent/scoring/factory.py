"""
Scorer factory and provider selection.

Priority order when creating a scorer:
  1. CLI flags  (--scoring-provider, --scoring-model)
  2. Environment variables  (SCORING_PROVIDER, SCORING_MODEL)
  3. Config file  (~/.job_agent/config.yaml)
  4. Interactive prompt  (if terminal is available)
  5. Default to mock scorer
"""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

from job_agent.scoring.base import ScorerBase

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "mock":   "job_agent.scoring.mock_scorer.MockScorer",
    "openai": "job_agent.scoring.openai_scorer.OpenAIScorer",
}


def _load_class(dotted_path: str):
    """Lazy-import a class by dotted path string."""
    module_path, cls_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


class ScorerFactory:
    """Factory for creating and configuring scorer instances."""

    @staticmethod
    def get_provider_names() -> list:
        return list(_PROVIDERS.keys())

    # ── Main entry point ──────────────────────────────────────────────────

    @staticmethod
    def create_from_cli_args(
        scoring_provider: Optional[str] = None,
        scoring_model: Optional[str] = None,
        interactive: bool = True,
    ) -> ScorerBase:
        """
        Create a scorer from CLI args, env vars, config, or interactively.

        Args:
            scoring_provider: From --scoring-provider flag (or None)
            scoring_model:    From --scoring-model flag (or None)
            interactive:      Prompt user if no provider found elsewhere

        Returns:
            Configured ScorerBase instance
        """
        # 1. CLI flags
        if scoring_provider:
            return ScorerFactory.create(scoring_provider, scoring_model)

        # 2. Environment variables
        env_provider = os.getenv("SCORING_PROVIDER")
        if env_provider:
            env_model = os.getenv("SCORING_MODEL")
            return ScorerFactory.create(env_provider, env_model)

        # 3. Config file
        cfg_provider, cfg_model = ScorerFactory._load_config()
        if cfg_provider:
            return ScorerFactory.create(cfg_provider, cfg_model)

        # 4. Interactive prompt
        if interactive:
            return ScorerFactory._interactive_selection()

        # 5. Default: mock
        logger.info("No scoring provider configured — defaulting to mock scorer")
        return ScorerFactory.create("mock")

    # ── Factory ───────────────────────────────────────────────────────────

    @staticmethod
    def create(provider: str, model: Optional[str] = None) -> ScorerBase:
        """
        Instantiate a scorer by provider name.

        Args:
            provider: "mock" | "openai"
            model:    Provider-specific model name (optional)

        Returns:
            Configured ScorerBase instance

        Raises:
            ValueError: Unknown provider or invalid configuration
        """
        provider = provider.strip().lower()

        if provider not in _PROVIDERS:
            raise ValueError(
                f"Unknown scoring provider: {provider!r}. "
                f"Available: {', '.join(_PROVIDERS)}"
            )

        cls = _load_class(_PROVIDERS[provider])

        if provider == "openai":
            scorer = cls(model=model or "gpt-4o")
        else:
            scorer = cls()

        if not scorer.validate_config():
            raise ValueError(
                f"Scorer configuration invalid for provider: {provider}"
            )

        logger.info(
            f"Scorer: {provider}"
            + (f" / {model}" if model and provider != "mock" else "")
        )
        return scorer

    # ── Interactive ───────────────────────────────────────────────────────

    @staticmethod
    def _interactive_selection() -> ScorerBase:
        """Prompt user to choose provider + model."""
        print("\n" + "═" * 60)
        print("  📊  Job Scoring Setup")
        print("═" * 60)

        providers = ScorerFactory.get_provider_names()
        print("\nSelect scoring backend:")
        for i, p in enumerate(providers, 1):
            desc = "Fast, offline — good for testing" if p == "mock" else "GPT — best results, needs API key"
            print(f"  {i}. {p:<10}  {desc}")

        selected = None
        while selected is None:
            try:
                raw = input(f"\nEnter choice (1-{len(providers)}): ").strip()
                idx = int(raw) - 1
                if 0 <= idx < len(providers):
                    selected = providers[idx]
                else:
                    print(f"  Enter a number between 1 and {len(providers)}")
            except (ValueError, EOFError):
                print("  Enter a number")

        model = None
        if selected == "openai":
            cls = _load_class(_PROVIDERS["openai"])
            models = cls.AVAILABLE_MODELS
            print(f"\nSelect OpenAI model:")
            for i, m in enumerate(models, 1):
                print(f"  {i}. {m}")
            while model is None:
                try:
                    raw = input(f"\nEnter choice (1-{len(models)}): ").strip()
                    idx = int(raw) - 1
                    if 0 <= idx < len(models):
                        model = models[idx]
                    else:
                        print(f"  Enter a number between 1 and {len(models)}")
                except (ValueError, EOFError):
                    print("  Enter a number")
            print(f"  ✅ Model: {model}")

        print(f"  ✅ Provider: {selected}")
        print("═" * 60 + "\n")
        return ScorerFactory.create(selected, model)

    # ── Config file ───────────────────────────────────────────────────────

    @staticmethod
    def _load_config() -> Tuple[Optional[str], Optional[str]]:
        """Load provider/model from ~/.job_agent/config.yaml."""
        config_path = Path.home() / ".job_agent" / "config.yaml"
        if not config_path.exists():
            return None, None
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            scoring = cfg.get("scoring", {})
            provider = scoring.get("provider")
            model = scoring.get("model")
            if provider:
                logger.debug(f"Config: provider={provider}, model={model}")
                return provider, model
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Could not read config: {e}")
        return None, None

    @staticmethod
    def save_config(provider: str, model: Optional[str] = None) -> None:
        """Persist provider/model to ~/.job_agent/config.yaml."""
        config_dir = Path.home() / ".job_agent"
        config_path = config_dir / "config.yaml"
        config_dir.mkdir(parents=True, exist_ok=True)
        try:
            import yaml
            cfg = {}
            if config_path.exists():
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
            cfg.setdefault("scoring", {})["provider"] = provider
            if model:
                cfg["scoring"]["model"] = model
            with open(config_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)
            logger.info(f"Saved scorer config: {provider} / {model}")
        except ImportError:
            logger.warning("pyyaml not installed — config not saved. Run: pip install pyyaml")
        except Exception as e:
            logger.warning(f"Could not save config: {e}")
