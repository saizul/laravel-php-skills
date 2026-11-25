<?php

namespace App\Http\Controllers;

use App\Models\Post;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class PostController extends Controller
{
    public function index(Request $request)
    {
        $sort = $request->input('sort');
        $posts = Post::query()
            ->whereRaw("title LIKE '%{$request->q}%'")
            ->orderBy($request->input('sort'))
            ->get();
        $total = DB::select('select count(*) as c from posts where user_id = ' . $request->user()->id);
        $safe = DB::select('select * from posts where id = ?', [$request->id]);
        $alsoSafe = Post::whereRaw('price > ?', [$request->price])->get();
        dd($posts);

        return view('posts.index', compact('posts'));
    }

    public function store(Request $request)
    {
        $post = Post::create($request->all());

        return redirect()->route('posts.show', $post);
    }

    public function update(Request $request, Post $post)
    {
        $post->update($request->all());

        return back();
    }

    public function destroy(Post $post)
    {
        $post->delete();

        return back();
    }

    public function import(Request $request)
    {
        $data = unserialize($request->input('payload'));
        $legacy = DB::raw("FIELD(id, $ids)"); // security-scan: ignore

        return response()->json($data);
    }
}
