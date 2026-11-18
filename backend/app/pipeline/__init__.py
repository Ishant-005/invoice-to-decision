"""The pipeline stages. Validate, Match, Rules and Decide are plain functions: they take data
in, return a typed result plus findings, and never touch the database, the network or the AI
model. Same inputs, same decision, every time."""
