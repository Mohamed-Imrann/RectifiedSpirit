# Contributing to SeriesBot

We welcome contributions to SeriesBot! Please follow these guidelines to help us maintain a clean and effective codebase.

## How to Contribute

1.  **Fork the Repository**: Start by forking the SeriesBot repository to your GitHub account.
2.  **Clone Your Fork**: Clone your forked repository to your local machine:
    \`\`\`bash
    git clone https://github.com/YOUR_USERNAME/SeriesBot.git
    \`\`\`
3.  **Create a New Branch**: Create a new branch for your feature or bug fix:
    \`\`\`bash
    git checkout -b feature/your-feature-name
    \`\`\`
    or
    \`\`\`bash
    git checkout -b bugfix/fix-description
    \`\`\`
4.  **Make Your Changes**: Implement your changes, ensuring they adhere to the existing code style and conventions.
5.  **Test Your Changes**: Before submitting, thoroughly test your changes to ensure they work as expected and don't introduce new issues.
6.  **Commit Your Changes**: Write clear and concise commit messages.
    \`\`\`bash
    git commit -m "feat: Add new feature"
    \`\`\`
    or
    \`\`\`bash
    git commit -m "fix: Resolve bug in X"
    \`\`\`
7.  **Push to Your Fork**: Push your changes to your forked repository:
    \`\`\`bash
    git push origin feature/your-feature-name
    \`\`\`
8.  **Create a Pull Request**: Open a pull request from your branch to the `main` branch of the original SeriesBot repository. Provide a detailed description of your changes.

## Code Style

*   Follow PEP 8 for Python code.
*   Use clear and descriptive variable and function names.
*   Add comments where necessary to explain complex logic.

## Reporting Bugs

If you find a bug, please open an issue on GitHub with the following information:
*   A clear and concise description of the bug.
*   Steps to reproduce the behavior.
*   Expected behavior.
*   Screenshots or error messages (if applicable).

Thank you for contributing!
\`\`\`

```plaintext file="Dockerfile"
FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "start.sh"]
