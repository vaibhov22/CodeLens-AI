async function askRepo() {

    const query = document.getElementById("query").value.trim();
    const repoPath = document.getElementById("repoPath").value.trim();
    const repoUrl = document.getElementById("repoUrl").value.trim();

    const loading = document.getElementById("loading");
    const responseBox = document.getElementById("responseBox");
    const answerEl = document.getElementById("answer");
    const fixEl = document.getElementById("fix");
    const fixTitle = document.getElementById("fixTitle");
    const sourcesEl = document.getElementById("sources");
    const warningsEl = document.getElementById("warnings");

    // ✅ Validation (at least one required)
    if (!query || (!repoPath && !repoUrl)) {
        alert("Enter query + (repo URL OR repo path)");
        return;
    }

    loading.classList.remove("hidden");
    responseBox.classList.add("hidden");

    try {

        let body = {
            query: query
        };

        // ✅ Priority: GitHub URL
        if (repoUrl !== "") {
            body.repo_url = repoUrl;
        } else {
            body.repo_path = repoPath;
        }

        const res = await fetch("/ask_repo", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body)
        });

        if (!res.ok) throw new Error("Server error");

        const data = await res.json();

        // -------- ANSWER --------
        answerEl.textContent = data.answer;

        // -------- FIX --------
        if (data.fix_code && data.fix_code.trim() !== "") {
            fixEl.textContent = data.fix_code;
            fixEl.classList.remove("hidden");
            fixTitle.classList.remove("hidden");
        } else {
            fixEl.classList.add("hidden");
            fixTitle.classList.add("hidden");
        }

        // -------- WARNINGS --------
        warningsEl.innerHTML = "";
        if (data.warnings && data.warnings.length > 0) {
            data.warnings.forEach(w => {
                const li = document.createElement("li");
                li.textContent = w;
                warningsEl.appendChild(li);
            });
        } else {
            warningsEl.innerHTML = "<li>No warnings</li>";
        }

        // -------- SOURCES --------
        sourcesEl.innerHTML = "";
        if (data.sources && data.sources.length > 0) {
            data.sources.forEach(src => {
                const li = document.createElement("li");
                li.textContent = `${src.file} → ${src.name}() [${src.start_line}-${src.end_line}]`;
                sourcesEl.appendChild(li);
            });
        } else {
            sourcesEl.innerHTML = "<li>No sources found</li>";
        }

        responseBox.classList.remove("hidden");

    } catch (err) {
        console.error(err);
        answerEl.textContent = "❌ Error connecting to backend.";
        responseBox.classList.remove("hidden");
    }

    loading.classList.add("hidden");
}