package dev.nxnative.android;
import java.io.File;
import java.util.ArrayDeque;
public final class BananaCheck {
 public static void main(String[] args) throws Exception {
  Nup nup=Nup.open(new File(args[0])); int files=0;
  for(Nup.Pkg pkg:nup.packages){
   ArrayDeque<Nup.Node> stack=new ArrayDeque<>(); stack.push(nup.dir(pkg.rootDir));
   while(!stack.isEmpty()){
    Nup.Node node=stack.pop(); if(node.dir)for(Nup.Node child:nup.children(node))stack.push(child);
    else { if(nup.read(node,-1).length!=node.size)throw new AssertionError("size"); files++; }
   }
  }
  Nup.Meta meta=nup.gameMeta();
  if(args.length>=3 && (!args[1].equals(meta.title)||!args[2].equals(meta.publisher)||meta.icon==null))throw new AssertionError("metadata");
  System.out.println("OK files="+files+" packages="+nup.packages.size()+" title="+meta.title+" publisher="+meta.publisher);
 }
}
