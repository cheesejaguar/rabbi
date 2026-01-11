# Contributing to rebbe.dev

Thank you for your interest in contributing to rebbe.dev! This project benefits from contributions by engineers, rabbis, Jewish educators, ethicists, and anyone passionate about the intersection of technology and Jewish wisdom.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Style Guidelines](#style-guidelines)
- [Testing](#testing)
- [Project Values](#project-values)

## Code of Conduct

This project is committed to providing a welcoming and inclusive environment. All contributors are expected to:

- Be respectful of differing viewpoints and experiences
- Accept constructive criticism gracefully
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Git

### Development Setup

1. **Fork the repository** on GitHub

2. **Clone your fork**

   ```bash
   git clone https://github.com/YOUR-USERNAME/rabbi.git
   cd rabbi
   ```

3. **Install uv** (if not already installed)

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

4. **Install dependencies** (including dev dependencies)

   ```bash
   uv sync --dev
   ```

5. **Set up environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

6. **Run the tests** to verify your setup

   ```bash
   uv run pytest
   ```

## Making Changes

### Branching Strategy

1. Create a new branch from `main` for your work:

   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```

2. Make your changes in small, focused commits

3. Write clear commit messages:

   ```
   Add pastoral context detection for grief scenarios

   - Add grief indicator keywords to pastoral agent
   - Update tone constraints for sensitive topics
   - Add tests for new detection logic
   ```

### Types of Contributions

We welcome many types of contributions:

- **Bug fixes** - Fix issues in the existing codebase
- **Features** - Add new functionality
- **Documentation** - Improve or add documentation
- **Tests** - Add or improve test coverage
- **Agent improvements** - Enhance the reasoning of existing agents
- **UI/UX** - Improve the frontend experience

## Pull Request Process

1. **Update documentation** if your changes affect usage

2. **Add tests** for any new functionality

3. **Run the full test suite** and ensure all tests pass:

   ```bash
   uv run pytest --cov=backend/app
   ```

4. **Push your branch** to your fork:

   ```bash
   git push origin feature/your-feature-name
   ```

5. **Open a Pull Request** against the `main` branch

6. **Fill out the PR template** with:
   - A clear description of the changes
   - The motivation for the changes
   - Any relevant issue numbers
   - Screenshots (if applicable)

7. **Address review feedback** promptly

### PR Requirements

- All CI checks must pass
- Code coverage should not decrease significantly
- At least one maintainer approval is required

## Style Guidelines

### Python

- Follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines
- Use type hints for function parameters and return values
- Write docstrings for public functions and classes
- Keep functions focused and reasonably sized

Example:

```python
async def process_message(
    self,
    user_message: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Process a user message through the agent pipeline.

    Args:
        user_message: The user's question or message
        conversation_history: Previous messages in the conversation

    Returns:
        dict containing response, metadata, and referral information
    """
    ...
```

### JavaScript

- Use modern ES6+ syntax
- Prefer `const` over `let` where possible
- Use meaningful variable and function names

### CSS

- Use CSS custom properties (variables) for theming
- Follow the existing naming conventions
- Keep styles modular and organized

### Commit Messages

- Use the imperative mood ("Add feature" not "Added feature")
- Keep the first line under 50 characters
- Add a blank line before detailed explanation if needed
- Reference issues with `#123` syntax

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=backend/app --cov-report=term-missing

# Run specific test file
uv run pytest backend/tests/test_pastoral.py -v

# Run tests matching a pattern
uv run pytest -k "test_crisis" -v
```

### Writing Tests

- Place tests in `backend/tests/`
- Name test files `test_*.py`
- Use descriptive test names that explain what is being tested
- Use pytest fixtures for common setup

Example:

```python
class TestPastoralContextAgent:
    """Test pastoral context analysis."""

    def test_detects_grief_indicators(self, mock_client):
        """Should detect grief when loss-related keywords present."""
        agent = PastoralContextAgent(mock_client)
        context = AgentContext(user_message="My father passed away last week")

        result = await agent.process(context)

        assert result.pastoral_context.mode == PastoralMode.COUNSELING
        assert result.pastoral_context.vulnerability_detected is True
```

### Test Coverage

We aim to maintain high test coverage. New code should include tests. Run coverage reports to identify untested code:

```bash
uv run pytest --cov=backend/app --cov-report=html
open htmlcov/index.html
```

## Project Values

When contributing to rebbe.dev, please keep these values in mind:

### Respect Halachic Pluralism

- Present multiple valid opinions, not just one
- Acknowledge minority views
- Avoid presenting any single approach as "the" answer

### Prioritize Human Dignity

- Consider the emotional impact of responses
- A technically correct answer that causes harm is a failure
- Vulnerable users deserve extra care

### Encourage Human Connection

- The AI should guide users toward human rabbis and communities
- Never position the AI as a replacement for human relationships
- Include appropriate disclaimers

### Avoid Absolutism

- Express uncertainty when appropriate
- Use "some opinions hold" rather than definitive statements
- Acknowledge the limits of AI in religious guidance

### No Ideological Gatekeeping

- Welcome contributions from across the Jewish spectrum
- Focus on technical and pastoral quality, not ideology
- Respect diverse approaches to Jewish life

## Questions?

If you have questions about contributing, feel free to:

- Open an issue for discussion
- Ask in the pull request comments

Thank you for helping make rebbe.dev better!
