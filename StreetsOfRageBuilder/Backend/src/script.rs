//! Running one of the project's Python scripts with its output streamed line by line.

use std::path::Path;
use std::process::Stdio;
use std::sync::Mutex;

use crate::{dependencies, system};

/// Run `scripts/<script> <args>` in the project folder. Every output line goes to `progress`;
/// a failure reports the last lines of output.
pub fn run(project: &Path, script: &str, args: &[&str], progress: &(dyn Fn(String) + Sync)) -> Result<(), String> {
    system::refresh_path();
    let path = project.join("scripts").join(script);
    if !path.is_file() {
        return Err(format!("{} is not the project folder; redo step 2.", project.display()));
    }
    let (python, leading) = dependencies::python_candidates()
        .into_iter()
        .next()
        .ok_or("Python was not found; finish step 1 first")?;
    let mut child = system::command(&python)
        .args(&leading)
        .arg(&path)
        .args(args)
        .current_dir(project)
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("could not start Python: {e}"))?;
    let stdout = child.stdout.take().expect("stdout is piped");
    let stderr = child.stderr.take().expect("stderr is piped");

    // Both streams feed the same progress line and the same tail kept for an error report.
    let tail = Mutex::new(Vec::<String>::new());
    let forward = |line: String| {
        progress(line.clone());
        let mut tail = tail.lock().unwrap();
        tail.push(line);
        if tail.len() > 12 {
            tail.remove(0);
        }
    };
    std::thread::scope(|scope| {
        scope.spawn(|| system::read_lines(stdout, &forward));
        system::read_lines(stderr, &forward);
    });

    let exit = child.wait().map_err(|e| e.to_string())?;
    if exit.success() {
        Ok(())
    } else {
        Err(format!("{script} failed ({exit})\n{}", tail.lock().unwrap().join("\n")))
    }
}
